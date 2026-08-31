"""全局串行发送队列。

同时满足以下约束：

- **全局串行**（需求 3）：所有群组共用一条发送通道，任何时刻只发一条消息。
  真人不可能在两个群里同时打字。
- **静默时段**（需求 4）：UTC+8 03:00–07:00 不发言，期间入队的消息直接丢弃
  （而不是攒到早上一次性喷发，那样更可疑）。
- **提及优先**（需求 5）：被 @ 或被回复的消息优先出队。
- **按需上线**（需求 10）：只在真正发送前上线，发完延迟下线。
- **打字模拟**（需求 3）：发送前按文本长度显示"正在输入…"。

队列采用优先级 + FIFO：同优先级内按入队顺序，跨优先级高优先先出。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

import asyncio
import heapq
import itertools
import random

# UTC+8
_CN_TZ = timezone(timedelta(hours=8))

# 优先级数值越小越先出队。
PRIORITY_MENTION = 0
"""被 @ 或被回复，最高优先级。"""

PRIORITY_NORMAL = 10
"""普通群聊消息。"""


@dataclass(order=True)
class _QueueItem:
    """队列中的一个发送任务。"""

    priority: int
    sequence: int
    action: Callable[[], Awaitable[Any]] = field(compare=False)
    future: asyncio.Future = field(compare=False)
    label: str = field(compare=False, default="")
    enqueued_at: float = field(compare=False, default=0.0)


def is_quiet_hours(
    now: Optional[datetime] = None,
    *,
    start_hour: int = 3,
    end_hour: int = 7,
) -> bool:
    """判断当前是否处于静默时段（UTC+8）。

    Args:
        now: 用于测试注入的时间；默认取当前 UTC+8 时间。
        start_hour: 静默开始小时（含）。
        end_hour: 静默结束小时（不含）。

    Returns:
        bool: 处于静默时段返回 ``True``。
    """

    current = now.astimezone(_CN_TZ) if now is not None else datetime.now(_CN_TZ)
    hour = current.hour

    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    # 跨零点的区间，例如 23:00 - 07:00
    return hour >= start_hour or hour < end_hour


def seconds_until_quiet_end(
    now: Optional[datetime] = None,
    *,
    end_hour: int = 7,
) -> float:
    """计算距离静默时段结束还有多少秒。

    Args:
        now: 用于测试注入的时间。
        end_hour: 静默结束小时。

    Returns:
        float: 剩余秒数。
    """

    current = now.astimezone(_CN_TZ) if now is not None else datetime.now(_CN_TZ)
    target = current.replace(hour=end_hour % 24, minute=0, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return (target - current).total_seconds()


class QuietHoursError(RuntimeError):
    """静默时段内拒绝发送时抛出。"""


class SendQueue:
    """全局串行、支持优先级与静默时段的发送队列。"""

    def __init__(
        self,
        logger: Any,
        *,
        quiet_start_hour: int = 3,
        quiet_end_hour: int = 7,
        enable_quiet_hours: bool = True,
        min_gap_seconds: float = 1.5,
        max_gap_seconds: float = 6.0,
    ) -> None:
        """初始化发送队列。

        Args:
            logger: 插件日志器。
            quiet_start_hour: 静默开始小时（UTC+8）。
            quiet_end_hour: 静默结束小时（UTC+8）。
            enable_quiet_hours: 是否启用静默时段。
            min_gap_seconds: 两条消息之间的最小间隔。
            max_gap_seconds: 两条消息之间的最大间隔。
        """

        self._logger = logger
        self._quiet_start_hour = quiet_start_hour
        self._quiet_end_hour = quiet_end_hour
        self._enable_quiet_hours = enable_quiet_hours
        self._min_gap = min_gap_seconds
        self._max_gap = max_gap_seconds

        self._heap: list[_QueueItem] = []
        self._counter = itertools.count()
        self._not_empty = asyncio.Event()
        self._worker: Optional[asyncio.Task[None]] = None
        self._running = False
        self._last_sent_at: float = 0.0

    def start(self) -> None:
        """启动后台发送协程。"""

        if self._running:
            return
        self._running = True
        self._worker = asyncio.create_task(self._run(), name="telegram_user_adapter.send_queue")

    async def stop(self) -> None:
        """停止发送协程并清空队列。"""

        self._running = False
        self._not_empty.set()

        worker = self._worker
        self._worker = None
        if worker is not None and not worker.done():
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

        while self._heap:
            item = heapq.heappop(self._heap)
            if not item.future.done():
                item.future.cancel()

    def in_quiet_hours(self, now: Optional[datetime] = None) -> bool:
        """判断当前是否静默。

        Args:
            now: 用于测试注入的时间。

        Returns:
            bool: 静默中返回 ``True``。
        """

        if not self._enable_quiet_hours:
            return False
        return is_quiet_hours(
            now,
            start_hour=self._quiet_start_hour,
            end_hour=self._quiet_end_hour,
        )

    async def submit(
        self,
        action: Callable[[], Awaitable[Any]],
        *,
        priority: int = PRIORITY_NORMAL,
        label: str = "",
    ) -> Any:
        """提交一个发送任务并等待其完成。

        Args:
            action: 实际执行发送的异步可调用对象。
            priority: 优先级，数值越小越先执行。
            label: 日志标签，通常是 chat_id。

        Returns:
            Any: ``action`` 的返回值。

        Raises:
            QuietHoursError: 当前处于静默时段。
            RuntimeError: 队列未启动。
        """

        if self.in_quiet_hours():
            remaining = seconds_until_quiet_end(end_hour=self._quiet_end_hour)
            self._logger.info(
                f"静默时段内丢弃发送请求 label={label}，距结束还有 {remaining / 60:.0f} 分钟"
            )
            raise QuietHoursError("当前处于静默时段，不发送消息")

        if not self._running:
            raise RuntimeError("发送队列尚未启动")

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        item = _QueueItem(
            priority=priority,
            sequence=next(self._counter),
            action=action,
            future=future,
            label=label,
            enqueued_at=loop.time(),
        )
        heapq.heappush(self._heap, item)
        self._not_empty.set()
        return await future

    async def _run(self) -> None:
        """后台串行执行队列中的发送任务。"""

        loop = asyncio.get_running_loop()
        while self._running:
            if not self._heap:
                self._not_empty.clear()
                try:
                    await self._not_empty.wait()
                except asyncio.CancelledError:
                    return
                continue

            item = heapq.heappop(self._heap)
            if item.future.cancelled():
                continue

            # 静默时段可能在排队期间到来，出队时重新检查。
            if self.in_quiet_hours():
                if not item.future.done():
                    item.future.set_exception(QuietHoursError("当前处于静默时段，不发送消息"))
                continue

            # 两条消息之间保持自然间隔，避免连珠炮。
            gap = random.uniform(self._min_gap, self._max_gap)
            elapsed = loop.time() - self._last_sent_at
            if self._last_sent_at > 0 and elapsed < gap:
                try:
                    await asyncio.sleep(gap - elapsed)
                except asyncio.CancelledError:
                    if not item.future.done():
                        item.future.cancel()
                    return

            try:
                result = await item.action()
            except asyncio.CancelledError:
                if not item.future.done():
                    item.future.cancel()
                raise
            except Exception as exc:  # noqa: BLE001 - 异常回传给提交方处理
                if not item.future.done():
                    item.future.set_exception(exc)
            else:
                if not item.future.done():
                    item.future.set_result(result)
            finally:
                self._last_sent_at = loop.time()

    @property
    def pending_count(self) -> int:
        """返回队列中待发送的任务数。

        Returns:
            int: 待发送任务数。
        """

        return len(self._heap)
