"""主动发言三选一（升级计划 Phase 6）：do_nothing / simple_bubble / throw_topic。

默认关闭。开启方式：编辑 ``data/maisaka_state/proactive.json``：

    {"enabled": true, "session_ids": ["<Host session_id>"], "daily_limit": 2}

只对 ``session_ids`` 白名单内的聊天流生效（灰度，先单一私聊/低风险群）。

触发条件（全部满足才可能非 do_nothing）：
- 冷场 ≥ 20 分钟（群友最后发言距今），且我们最近 60 分钟没说过话；
- 非深夜（Asia/Shanghai 08:00–23:30）；
- 不在冷却期（被拒绝 / 连续无人回应）；
- 当前没有 Planner 在运行；
- 今日主动次数未达上限；连续主动后无人回应则指数退避。

行为：
- simple_bubble：轻量一句，不引入新主题（能量/心情一般即可）；
- throw_topic：只有冷场 ≥ 60 分钟且能量、关系、心情都足够时。
最终是否说、说什么仍由 Planner 决定，并经过发送预算、权限、出站审查等全部闸门。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import json
import time

from src.maisaka.state_model.chat_state import get_state_store

CN_TZ = timezone(timedelta(hours=8))
_CONFIG = Path(__file__).resolve().parents[3] / "data" / "maisaka_state" / "proactive.json"
_LEDGER = Path(__file__).resolve().parents[3] / "data" / "maisaka_state" / "proactive_ledger.json"

IDLE_BUBBLE_SECONDS = 20 * 60
IDLE_TOPIC_SECONDS = 60 * 60
SELF_QUIET_SECONDS = 60 * 60


@dataclass(frozen=True)
class ProactiveDecision:
    action: str  # do_nothing / simple_bubble / throw_topic
    reason: str = ""
    prompt: str = ""


def _load_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)


def _ledger_today(session_id: str) -> dict:
    ledger = _load_json(_LEDGER, {})
    today = datetime.now(CN_TZ).strftime("%Y-%m-%d")
    entry = ledger.get(session_id) or {}
    if entry.get("date") != today:
        entry = {"date": today, "count": 0, "last_unix": entry.get("last_unix", 0.0),
                 "ignored_streak": entry.get("ignored_streak", 0)}
    return entry


def mark_proactive_sent(session_id: str) -> None:
    ledger = _load_json(_LEDGER, {})
    entry = _ledger_today(session_id)
    entry["count"] += 1
    entry["last_unix"] = time.time()
    entry["ignored_streak"] = entry.get("ignored_streak", 0) + 1  # 有人回应时由状态清零
    ledger[session_id] = entry
    _LEDGER.parent.mkdir(parents=True, exist_ok=True)
    _LEDGER.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")


def decide_proactive(session_id: str, *, is_group: bool, agent_running: bool) -> ProactiveDecision:
    config = _load_json(_CONFIG, {"enabled": False})
    if not config.get("enabled") or session_id not in set(config.get("session_ids") or []):
        return ProactiveDecision("do_nothing")
    if agent_running:
        return ProactiveDecision("do_nothing", "planner_running")

    now_cn = datetime.now(CN_TZ)
    minutes = now_cn.hour * 60 + now_cn.minute
    if not (8 * 60 <= minutes <= 23 * 60 + 30):
        return ProactiveDecision("do_nothing", "night")

    store = get_state_store()
    state = store.get(session_id)
    mono = time.monotonic()
    if mono < state.cooldown_until_mono:
        return ProactiveDecision("do_nothing", "cooldown")
    if state.last_external_mono <= 0:
        return ProactiveDecision("do_nothing", "no_recent_activity")  # 重启后需先见到真实发言
    idle = mono - state.last_external_mono
    if idle < IDLE_BUBBLE_SECONDS:
        return ProactiveDecision("do_nothing", "not_idle")
    if state.last_self_mono > 0 and mono - state.last_self_mono < SELF_QUIET_SECONDS:
        return ProactiveDecision("do_nothing", "spoke_recently")
    if idle > 6 * 3600:
        return ProactiveDecision("do_nothing", "chat_dead")  # 群已散，不对空气说话

    entry = _ledger_today(session_id)
    if entry["count"] >= int(config.get("daily_limit", 2)):
        return ProactiveDecision("do_nothing", "daily_limit")
    # 有新的群友发言出现在上次主动之后 → 视为没被无视。
    if entry.get("last_unix") and state.last_external_mono > 0:
        last_external_unix = time.time() - idle
        if last_external_unix > entry["last_unix"]:
            entry["ignored_streak"] = 0
    backoff = IDLE_BUBBLE_SECONDS * (2 ** min(4, entry.get("ignored_streak", 0)))
    if entry.get("last_unix") and time.time() - entry["last_unix"] < backoff:
        return ProactiveDecision("do_nothing", "ignored_backoff")

    if state.energy < 0.5 or state.valence < -0.2:
        return ProactiveDecision("do_nothing", "low_energy_or_mood")

    rapport = max(state.rapport.values()) if state.rapport else 0.0
    if idle >= IDLE_TOPIC_SECONDS and state.energy >= 0.7 and state.valence >= 0.1 and rapport >= 0.2:
        return ProactiveDecision(
            "throw_topic",
            f"冷场{int(idle // 60)}分钟",
            "群里冷场挺久了。如果你真有一个自然的、和最近聊过的话题相关的小想法，可以随口抛一句；"
            "没有就什么都不发。只发一条短句，不要问候、不要总结、不要客服腔。",
        )
    return ProactiveDecision(
        "simple_bubble",
        f"冷场{int(idle // 60)}分钟",
        "群里安静了一阵。只有当你确实有一句很轻的接话（接最近的话题，不开新话题）时才说一句；"
        "大多数情况下应当什么都不发。不要问候、不要“大家在干嘛”、不要表情包式凑数。",
    )
