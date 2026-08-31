"""全局发送预算：限制单位时间的出站总量。

为什么需要这个模块
------------------

2026-08-31 账号被 Telegram 反垃圾系统限制。当天出站 533 条，
15 时单小时 107 条。

最初我把封禁归因为"总量太大"，后来实测推翻了这个判断：
真人单群小时峰值最高 80 条、前 10 名平均 68.9 条，天天水群的人
确实能到这个量级。**真正异常的是分布**——我方那 107 条散在
12 个群里，而 1128 条真人记录中跨 ≥3 群的为 0。
那部分防护在 ``attention_focus`` 模块。

本模块仍有价值，但定位变了：它防的是"爆发式连发"这种局部异常，
上限对齐真人水平（60 条/小时、5 条/分钟）而非刻意压低。

此前所有防护都是**单群维度**：
- ``small_chat.MIN_REPLY_GAP_SECONDS`` 管单群两次发言间隔
- ``small_chat.SMALL_CHAT_REPLY_RATIO`` 管单群参与率
- ``engagement`` 管单群权重

全局总量没有任何人负责，这才是本模块补上的那一维。
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, Optional, Tuple

import time

# 每小时全局发送上限。
#
# 最初设 30 条，依据是"封禁前峰值 107 条太高"。后来实测推翻了这个
# 判断：样本 563 个真人中，单群小时峰值最高 80 条、前 10 名平均
# 68.9 条——天天水群的人确实能到这个量级，30 条反而会让账号
# 显得反常沉默。
#
# 取 60 条：贴近真人前 10 名的平均峰值，仍留出对 80 条天花板的余量。
# 真正防"同时在十几个群活跃"这个异常模式的是 attention_focus 模块，
# 那才是实测中真人从不出现的行为（跨 ≥3 群记录 0/1128）。
DEFAULT_HOURLY_LIMIT = 60

# 每分钟全局发送上限。
#
# 光有小时限额挡不住爆发式连发——60 条挤在几分钟内发完同样异常。
# 取 5 条：允许一次回复拆成 2-3 段（真人常见），也容得下真人
# 在单群里的连续接话，但挡住持续刷屏。
DEFAULT_MINUTE_LIMIT = 5

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
