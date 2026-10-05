"""Planner 运行中追加消息的合并与打断策略（升级计划 Phase 2）。

原行为：``planner_interrupt_max_consecutive_count = 0``，Planner 运行时到达的
新消息只能等本轮自然结束；改成 >0 后则任何新消息都会打断重想。

新策略：
- 一次运行最多 1 次打断（配置 ``planner_interrupt_max_consecutive_count = 1``）。
- 只有"高优先级新信息"才打断：被 @/提及、纠正事实、明确改变任务、
  回答我们刚提出的问题；其余消息进入缓冲，在下一工具边界按到达顺序合并。
- 合并窗口：静默期最长 8 秒，或累计到 3 条立即合并，避免一直等。
"""

from typing import Optional

import re

FOLLOW_UP_MAX_MESSAGES = 3
FOLLOW_UP_MAX_WINDOW_SECONDS = 8.0

_CORRECTION = re.compile(
    r"^(?:不是|不对|错了|搞错|我说的是|我是说|我的意思是|不是这个意思|更正|纠正|说反了|打错了)"
)
_TASK_CHANGE = re.compile(r"^(?:算了|不用了|别管|换个|改成|改为|先别|等等|停一下|别回)")


def _strip(text: str) -> str:
    text = re.sub(r"^\[回复[^\]]*\]，说：", "", (text or "").strip())
    return re.sub(r"@\S+\s*", "", text).strip()


def follow_up_priority(
    *,
    text: str,
    is_at: bool,
    is_mentioned: bool,
    answers_our_question: bool = False,
) -> Optional[str]:
    """返回高优先级原因；普通追加消息返回 ``None``（只合并，不打断）。"""

    if is_at or is_mentioned:
        return "mention"
    core = _strip(text)
    if _CORRECTION.search(core):
        return "correction"
    if _TASK_CHANGE.search(core):
        return "task_change"
    if answers_our_question:
        return "answer"
    return None


def merge_window_reached(*, pending_count: int, first_pending_at: float, now: float) -> bool:
    """追加消息是否已达到合并条件（3 条或 8 秒）。"""

    if pending_count >= FOLLOW_UP_MAX_MESSAGES:
        return True
    return first_pending_at > 0 and now - first_pending_at >= FOLLOW_UP_MAX_WINDOW_SECONDS
