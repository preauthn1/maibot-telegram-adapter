"""注意力焦点：限制同一时间窗内活跃的群数。

为什么需要这个模块
------------------

2026-08-31 账号被 Telegram 反垃圾系统限制。最初我归因为「15 时
单小时发了 107 条，量太大」，并据此把全局总量掐到 30 条/小时。
用户质疑这个判断，实测后证明我错了：

样本 4 个群、563 个真人发言者、1128 条「用户×小时」记录：

- 真人单群小时峰值最高 **80 条**，前 10 名平均 **68.9 条**
- 峰值 ≥107 条的真人：**0/563**（所以 107 确实偏高，但同量级）
- 单小时跨 ≥3 个群发言的真人：**0/1128**
- 前 15 名高发言者：14 个只在 1 个群，1 个在 2 个群

真正的异常不是总量，而是**分布**。我方那 107 条散在 12 个群里，
而真人水群永远是扎在一两个群里聊——人的注意力是独占的，
不可能同一小时同时跟十几个互不相关的话题。
「一个人同时活跃在 12 个群」在行为特征上极其扎眼。

因此本模块限制的是「同时在场群数」，并让账号像真人那样
在一段时间内**聚焦少数几个群**，窗口过后再自然转移。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import time

from .unlimited_mode import is_unlimited

# 同一时间窗内最多在几个群活跃。
#
# 真人实测最多观测到 2 个群（1128 条记录中跨 ≥3 群的为 0）。
# 取 2 与实测一致；留 3 作为可配上限，不建议超过。
DEFAULT_MAX_CONCURRENT_CHATS = 2

# 注意力窗口（秒）。
#
# 30 分钟：真人在一个群聊一阵子后转去别的群是自然的，
# 但不会每隔几分钟就在十几个群之间轮转。
#
# 取值依据：用封禁当天 533 条真实出站回放对比两档窗口——
#   30 分钟 → 单小时最大跨群 3、总量峰值 40
#   15 分钟 → 单小时最大跨群 4、总量峰值 48
# 真人实测基准是跨群 ≤2，所以宁可牺牲一点总量也要压住并发：
# 「同时在多个群活跃」才是实测中真人从不出现的模式，
# 而总量偏低只是显得沉默，不构成机器特征。
DEFAULT_FOCUS_WINDOW_SECONDS = 1800.0


class AttentionFocus:
    """跟踪当前处于注意力焦点的会话，超出并发上限时拒绝新会话。"""

    def __init__(
        self,
        *,
        max_concurrent_chats: int = DEFAULT_MAX_CONCURRENT_CHATS,
        focus_window_seconds: float = DEFAULT_FOCUS_WINDOW_SECONDS,
    ) -> None:
        """初始化注意力焦点跟踪器。

        Args:
            max_concurrent_chats: 同一窗口内最多活跃的会话数。
            focus_window_seconds: 一个会话保持"在焦点内"的时长。
        """

        self.max_concurrent_chats = max_concurrent_chats
        self.focus_window_seconds = focus_window_seconds
        # chat_id -> 最近一次在该会话发言的时间
        self._last_active: Dict[str, float] = {}

    def _prune(self, now: float) -> None:
        """移出窗口外的会话，让注意力可以自然转移。"""

        cutoff = now - self.focus_window_seconds
        for chat_id in [
            key for key, stamp in self._last_active.items() if stamp < cutoff
        ]:
            del self._last_active[chat_id]

    def check(
        self, chat_id: str, *, now: Optional[float] = None
    ) -> Tuple[bool, str]:
        """判断此刻是否允许在该会话发言。

        Args:
            chat_id: 目标会话 ID。
            now: 单调时钟读数，便于测试注入。

        Returns:
            Tuple[bool, str]: ``(是否允许, 拒绝原因)``；允许时原因为空串。
        """

        current = now if now is not None else time.monotonic()
        self._prune(current)

        # 已在焦点内的会话继续放行：真人会在同一个群持续聊下去。
        if chat_id in self._last_active:
            return True, ""

        # 极端实验模式：不再限制并发会话数。
        # 注意单群场景下这一层本就不会触发（只有 1 个会话），
        # 解除它主要是为了让实验条件干净——不留任何频率类拦截。
        if is_unlimited():
            return True, ""

        if len(self._last_active) >= self.max_concurrent_chats:
            active = len(self._last_active)
            return False, (
                f"注意力已占满 {active}/{self.max_concurrent_chats} 个会话，"
                "真人不会同时在多个群活跃"
            )
        return True, ""

    def record(self, chat_id: str, *, now: Optional[float] = None) -> None:
        """记录一次在该会话的实际发言。

        Args:
            chat_id: 目标会话 ID。
            now: 单调时钟读数。
        """

        if not chat_id:
            return

        current = now if now is not None else time.monotonic()
        self._prune(current)
        self._last_active[chat_id] = current

    def stats(self, *, now: Optional[float] = None) -> Dict[str, int]:
        """返回当前焦点占用情况，便于日志与巡检。

        Args:
            now: 单调时钟读数。

        Returns:
            Dict[str, int]: 含 ``active_chats`` 与 ``max_concurrent_chats``。
        """

        current = now if now is not None else time.monotonic()
        self._prune(current)
        return {
            "active_chats": len(self._last_active),
            "max_concurrent_chats": self.max_concurrent_chats,
        }
