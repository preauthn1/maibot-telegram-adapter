"""web_search 内置工具。

用途：聊天中遇到不认识的新名词、新事件、时效性问题时联网查一下，
避免硬编或者说"不知道"——这两种反应都不像真人。

用 Tavily API。key 存在 ``config/.tavily_api_keys``（每行一个），
支持多个 key 轮换：单个 key 免费额度有限，轮换能摊平用量，
且某个 key 失效时自动跳到下一个。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import asyncio
import itertools
import json
import urllib.error
import urllib.request

from src.common.logger import get_logger
from src.core.tooling import ToolExecutionContext, ToolExecutionResult, ToolInvocation, ToolSpec

from .context import BuiltinToolRuntimeContext

logger = get_logger("maisaka_builtin_web_search")

_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_KEY_FILE = Path("config/.tavily_api_keys")
_REQUEST_TIMEOUT = 15.0

# key 轮换游标。模块级保持，让多次调用能真正轮着用。
_key_cycle: Optional[itertools.cycle] = None
_cached_keys: List[str] = []


def _load_keys() -> List[str]:
    """读取 Tavily API key 列表。

    Returns:
        List[str]: key 列表；文件不存在时返回空列表。
    """

    global _cached_keys, _key_cycle

    if _cached_keys:
        return _cached_keys

    if not _KEY_FILE.exists():
        logger.warning(f"未找到 Tavily key 文件: {_KEY_FILE}")
        return []

    keys = [
        line.strip()
        for line in _KEY_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    _cached_keys = keys
    _key_cycle = itertools.cycle(keys) if keys else None
    return keys


def _next_key() -> Optional[str]:
    """取下一个 API key（轮换）。

    Returns:
        Optional[str]: 可用的 key；没有配置时返回 ``None``。
    """

    keys = _load_keys()
    if not keys:
        return None
    if _key_cycle is None:
        return keys[0]
    return next(_key_cycle)


def get_tool_spec() -> ToolSpec:
    """获取 web_search 工具声明。"""

    return ToolSpec(
        name="web_search",
        description=(
            "联网搜索。遇到不认识的新名词、新产品、突发事件，"
            "或需要确认时效性信息时使用。不要用它查你已经知道的常识。"
        ),
        parameters_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词。用最短的有效表述，不要写成整句问话。",
                },
                "max_results": {
                    "type": "integer",
                    "description": "返回结果条数，默认 3。",
                    "minimum": 1,
                    "maximum": 5,
                },
            },
            "required": ["query"],
        },
        provider_name="maisaka_builtin",
        provider_type="builtin",
    )


def _do_search(query: str, api_key: str, max_results: int) -> Dict[str, Any]:
    """执行一次同步 HTTP 搜索请求。

    放在线程里跑，避免阻塞事件循环。

    Args:
        query: 搜索词。
        api_key: Tavily API key。
        max_results: 结果条数。

    Returns:
        Dict[str, Any]: Tavily 返回的 JSON。

    Raises:
        urllib.error.HTTPError: HTTP 层错误（如 401/429）。
        urllib.error.URLError: 网络不可达。
    """

    payload = json.dumps(
        {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
            "include_answer": True,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        _TAVILY_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _format_results(data: Dict[str, Any], max_results: int) -> str:
    """把搜索结果整理成简短文本。

    结果会进入 LLM 上下文，所以要短——只保留能回答问题的部分，
    塞太多正文会挤掉真正的聊天上下文。

    Args:
        data: Tavily 响应。
        max_results: 最多保留几条。

    Returns:
        str: 格式化文本。
    """

    lines: List[str] = []

    answer = data.get("answer")
    if isinstance(answer, str) and answer.strip():
        lines.append(f"结论：{answer.strip()}")

    results = data.get("results")
    if isinstance(results, list):
        for item in results[:max_results]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip()
            if not title and not content:
                continue
            # 单条正文截断，避免长文档淹没上下文。
            snippet = content[:200]
            lines.append(f"- {title}：{snippet}")

    return "\n".join(lines) if lines else "没有搜到有效结果。"


async def handle_tool(
    tool_ctx: BuiltinToolRuntimeContext,
    invocation: ToolInvocation,
    context: Optional[ToolExecutionContext] = None,
) -> ToolExecutionResult:
    """执行 web_search 内置工具。"""

    del context

    raw_query = invocation.arguments.get("query")
    if not isinstance(raw_query, str) or not raw_query.strip():
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "web_search 需要提供非空的 `query` 字符串参数。",
        )
    query = raw_query.strip()

    raw_max = invocation.arguments.get("max_results", 3)
    try:
        max_results = max(1, min(5, int(raw_max)))
    except (TypeError, ValueError):
        max_results = 3

    keys = _load_keys()
    if not keys:
        return tool_ctx.build_failure_result(
            invocation.tool_name,
            "未配置 Tavily API key，无法联网搜索。",
        )

    # 逐个 key 尝试：某个 key 额度用尽或失效时换下一个。
    # 不做无限重试——最多把所有 key 试一遍。
    last_error = ""
    for _ in range(len(keys)):
        api_key = _next_key()
        if not api_key:
            break
        try:
            data = await asyncio.to_thread(_do_search, query, api_key, max_results)
        except urllib.error.HTTPError as exc:
            # 401/403 是 key problem，429 是限流，都换下一个 key 重试。
            last_error = f"HTTP {exc.code}"
            logger.warning(f"[web_search] key 调用失败({exc.code})，尝试下一个")
            continue
        except urllib.error.URLError as exc:
            last_error = f"网络错误: {exc.reason}"
            logger.warning(f"[web_search] 网络不可达: {exc.reason}")
            break
        except (TimeoutError, json.JSONDecodeError) as exc:
            last_error = f"{type(exc).__name__}"
            logger.warning(f"[web_search] 响应异常: {exc}")
            break

        formatted = _format_results(data, max_results)
        logger.info(f"[web_search] 查询完成: {query!r}")
        return tool_ctx.build_success_result(
            invocation.tool_name,
            formatted,
            metadata={"query": query, "result_count": max_results},
        )

    return tool_ctx.build_failure_result(
        invocation.tool_name,
        f"搜索失败：{last_error or '所有 API key 均不可用'}。",
    )
