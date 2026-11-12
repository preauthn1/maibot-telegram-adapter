"""sports_schedule 内置工具。

用途：查询美国职业联赛（NBA/NFL/MLB/NHL/WNBA）某一天的赛程与比分。

为什么单独做：
- 搜索引擎对"今天赛程"常返回视频、社交贴文、旧赛季页面；
- cdn.nba.com 对本机出口返回 403；
- fetch_url 读 ESPN JSON 时超过 8KB 会截断，前 8KB 只有日历元数据，赛程被丢掉。
因此直接请求 ESPN scoreboard 接口，只返回紧凑的对阵列表，并统一换算北京时间。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import asyncio
import json

import aiohttp

from src.common.logger import get_logger
from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec

from .context import BuiltinToolRuntimeContext

logger = get_logger("maisaka_builtin_sports_schedule")

_ENDPOINT = "https://site.api.espn.com/apis/site/v2/sports/{sport}/{league}/scoreboard"
_LEAGUES = {
    "nba": ("basketball", "nba"),
    "wnba": ("basketball", "wnba"),
    "nfl": ("football", "nfl"),
    "mlb": ("baseball", "mlb"),
    "nhl": ("hockey", "nhl"),
}
_CN_TZ = timezone(timedelta(hours=8))
_ET_TZ = timezone(timedelta(hours=-4))  # 美东夏令时；冬令时偏差 1 小时只影响"哪天"的边界判断
_TIMEOUT = 12.0
_MAX_BYTES = 4 * 1024 * 1024


def get_tool_spec() -> ToolSpec:
    """获取 sports_schedule 工具声明。"""

    return ToolSpec(
        name="sports_schedule",
        description=(
            "查询 NBA/WNBA/NFL/MLB/NHL 指定日期的赛程、比分和比赛状态（数据源 ESPN）。"
            "用户问\"今天/明天的比赛、赛程、比分\"时优先用它，不要用 web_search 搜赛程。"
            "date 填北京时间日期（YYYY-MM-DD）；不填默认北京时间今天。返回的时间已换算为北京时间。"
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "league": {
                    "type": "string",
                    "enum": sorted(_LEAGUES),
                    "description": "联赛，默认 nba。",
                },
                "date": {
                    "type": "string",
                    "description": "北京时间日期 YYYY-MM-DD；默认今天。",
                },
            },
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
    )


async def _fetch(url: str, params: Dict[str, str]) -> Dict[str, Any]:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=_TIMEOUT)) as session:
        async with session.get(url, params=params, allow_redirects=False) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > _MAX_BYTES:
                    raise ValueError("response_too_large")
            return json.loads(body.decode("utf-8"))


def _team(competitor: Dict[str, Any]) -> str:
    team = competitor.get("team") or {}
    return str(team.get("displayName") or team.get("name") or "?")


def _events_for_cn_date(events: List[Dict[str, Any]], cn_date: str) -> List[Dict[str, Any]]:
    """筛出开赛时间落在指定北京时间日期的比赛。"""

    picked = []
    for event in events:
        raw = str(event.get("date") or "")
        try:
            start = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(_CN_TZ)
        except ValueError:
            continue
        if start.strftime("%Y-%m-%d") == cn_date:
            picked.append((start, event))
    picked.sort(key=lambda pair: pair[0])
    return [{"start": start, "event": event} for start, event in picked]


def _format_game(start: datetime, event: Dict[str, Any]) -> str:
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})
    status = ((competition.get("status") or {}).get("type") or {})
    state = status.get("state")
    line = f"{start.strftime('%H:%M')} {_team(away)} @ {_team(home)}"
    if state == "post":
        line += f"（已结束 {away.get('score', '?')}-{home.get('score', '?')}）"
    elif state == "in":
        line += f"（进行中 {away.get('score', '?')}-{home.get('score', '?')} {status.get('shortDetail', '')}）"
    return line


async def handle_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: ToolExecutionContext | None = None,
) -> ToolExecutionResult:
    """执行赛程查询。"""

    del context
    league = str(invocation.arguments.get("league") or "nba").strip().lower()
    if league not in _LEAGUES:
        return tool_ctx.build_failure_result(invocation.tool_name, f"不支持的联赛：{league}")

    raw_date = str(invocation.arguments.get("date") or "").strip()
    if raw_date:
        try:
            cn_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            return tool_ctx.build_failure_result(invocation.tool_name, "date 需要 YYYY-MM-DD 格式。")
    else:
        cn_date = datetime.now(_CN_TZ).strftime("%Y-%m-%d")

    # 北京时间某天的比赛，开赛时美东可能是前一天或当天，两天都查再按北京时间筛。
    cn_day = datetime.strptime(cn_date, "%Y-%m-%d")
    et_days = [(cn_day - timedelta(days=1)).strftime("%Y%m%d"), cn_day.strftime("%Y%m%d")]
    sport, league_path = _LEAGUES[league]
    url = _ENDPOINT.format(sport=sport, league=league_path)

    events: List[Dict[str, Any]] = []
    seen: set[str] = set()
    try:
        results = await asyncio.gather(*(_fetch(url, {"dates": day}) for day in et_days))
    except (aiohttp.ClientError, TimeoutError, asyncio.TimeoutError, ValueError) as exc:
        logger.warning(f"[sports_schedule] 查询失败: {type(exc).__name__}")
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "这次赛程接口请求失败，尚未核实。",
            metadata={"search_status": "failed", "reason_code": type(exc).__name__},
        )
    for data in results:
        for event in data.get("events") or []:
            event_id = str(event.get("id") or "")
            if event_id and event_id not in seen:
                seen.add(event_id)
                events.append(event)

    games = _events_for_cn_date(events, cn_date)
    header = f"{league.upper()} 北京时间 {cn_date} 赛程（来源 ESPN，时间为北京时间，客队 @ 主队）："
    if not games:
        text = header + "\n当天没有比赛。"
    else:
        text = header + "\n" + "\n".join(f"- {_format_game(g['start'], g['event'])}" for g in games)
        text += f"\n共 {len(games)} 场。"
    logger.info(f"[sports_schedule] 查询完成: {league} {cn_date} 共 {len(games)} 场")
    return tool_ctx.build_success_result(
        invocation.tool_name,
        text,
        metadata={"search_status": "ok", "result_count": len(games), "league": league, "cn_date": cn_date},
    )
