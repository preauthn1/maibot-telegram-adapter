"""全局发送预算：限制单位时间的出站总量。

为什么需要这个模块
------------------

2026-08-31 账号被 Telegram 反垃圾系统限制。事后复盘：

- 04:02 SpamBot 回复 "no limits are currently applied"
- 16:42 SpamBot 回复 "your account was limited"
- 期间本地 transcript 出站 517 条，15 时单小时 107 条

此前的所有防护都是**局部维度**：
- ``small_chat.MIN_REPLY_GAP_SECONDS`` 管单群两次发言间隔
- ``small_chat.SMALL_CHAT_REPLY_RATIO`` 管单群参与率
- ``engagement`` 管单群权重

每一项单独看都合规，但十几个群并发时，全局总量没有任何人负责。
间隔 9 秒 × 12 个群 = 理论上每小时能发数百条，而真人一小时
在群里发 107 条是不可能的——这正是触发封禁的直接原因。

本模块补上缺失的那一维：不关心是哪个群，只管单位时间总量。
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Optional, Tuple

import time

# 每小时全局发送上限。
#
# 封禁前峰值是 107 条/小时。取 30 条：按真人在多个群里活跃的水平，
# 一小时几十条已属健谈，且远离触发阈值。
DEFAULT_HOURLY_LIMIT = 30

# 每分钟全局发送上限。
#
# 光有小时限额挡不住爆发式连发——30 条挤在两分钟内发完同样异常。
# 取 4 条：允许一次回复拆成 2-3 段（真人常见），但挡住持续刷屏。
DEFAULT_MINUTE_LIMIT = 4

_HOUR_SECONDS = 3600.0
_MINUTE_SECONDS = 60.0


class SendBudget:
    """跟踪全局出站量并在超额时拒绝发送。"""

    def __init__(
        self,
        *,
        hourly_limit: int = DEFAULT_HOURLY_LIMIT,
        minute_limit: int = DEFAULT_MINUTE_LIMIT,
    ) -> None:
        """初始化预算跟踪器。

        Args:
            hourly_limit: 每小时最多发送多少条。
            minute_limit: 每分钟最多发送多少条。
        """

        self.hourly_limit = hourly_limit
        self.minute_limit = minute_limit
        self._sends: Deque[float] = deque()

    def _prune(self, now: float) -> None:
        """丢弃一小时之前的记录，保持内存有界。"""

        cutoff = now - _HOUR_SECONDS
        while self._sends and self._sends[0] < cutoff:
            self._sends.popleft()

    def _counts(self, now: float) -> Tuple[int, int]:
        """返回最近一小时与最近一分钟的发送数。"""

        self._prune(now)
        minute_cutoff = now - _MINUTE_SECONDS
        last_minute = sum(1 for stamp in self._sends if stamp >= minute_cutoff)
        return len(self._sends), last_minute

    def check(self, *, now: Optional[float] = None) -> Tuple[bool, str]:
        """判断此刻是否还允许发送。

        Args:
            now: 单调时钟读数，便于测试注入。

        Returns:
            Tuple[bool, str]: ``(是否允许, 拒绝原因)``；允许时原因为空串。
        """

        current = now if now is not None else time.monotonic()
        last_hour, last_minute = self._counts(current)

        if last_minute >= self.minute_limit:
            return False, (
                f"每分钟发送上限已满 {last_minute}/{self.minute_limit}"
            )
        if last_hour >= self.hourly_limit:
            return False, (
                f"每小时发送上限已满 {last_hour}/{self.hourly_limit}"
            )
        return True, ""

    def record(self, *, now: Optional[float] = None) -> None:
        """记录一次实际发送。

        Args:
            now: 单调时钟读数。
        """

        current = now if now is not None else time.monotonic()
        self._sends.append(current)
        self._prune(current)

    def stats(self, *, now: Optional[float] = None) -> Dict[str, int]:
        """返回当前用量，便于日志与巡检。

        Args:
            now: 单调时钟读数。

        Returns:
            Dict[str, int]: 含 ``last_hour``/``last_minute`` 与两个上限。
        """

        current = now if now is not None else time.monotonic()
        last_hour, last_minute = self._counts(current)
        return {
            "last_hour": last_hour,
            "last_minute": last_minute,
            "hourly_limit": self.hourly_limit,
            "minute_limit": self.minute_limit,
        }
