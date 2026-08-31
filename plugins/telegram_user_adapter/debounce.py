"""入站防抖：把连续到达的消息聚合成一次处理。

为什么需要这个模块
------------------

我们此前每条入站消息都单独进决策、单独回复。真人不是这样的：
群里连着来五句，人会读完再回一次，不会逐条应答。

2026-08-31 账号因用户举报被封（SpamBot 明确是「经我们的审核员
确认」），逐条机械响应比发言总量更能解释"为什么被看出不是真人"——
一个"人"对每句话都在 10 秒内给出针对性回复，这本身就不正常。

思路移植自 AEsirClaw 的 ``Debouncer``，但改了两处：

1. 参考实现缓存的是**协程**，覆盖候选时用 ``pop()`` 直接丢弃，
   未 await 的 coroutine 会泄漏并触发 RuntimeWarning。
   这里缓存**消息数据**，聚合完成后一次性交给回调。
2. 参考实现固定 ``delay``，这里加入抖动：固定等待时长本身
   就是可识别的自动化特征。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Awaitable, Callable, DefaultDict, Dict, List, Optional

import asyncio
import random

# 默认聚合等待时长（秒）。
#
# 5 秒：真人读完一条群消息再决定要不要回，通常就是几秒量级。
# 太短失去聚合意义，太长会让回复显得脱节。
DEFAULT_DELAY_SECONDS = 5.0

# 等待时长的随机抖动上限（秒）。
DEFAULT_JITTER_SECONDS = 2.5

FlushCallback = Callable[[List[str]], Awaitable[None]]


class InboundDebouncer:
    """按会话聚合入站消息，等待静默后一次性处理。"""

    def __init__(
        self,
        *,
        delay: float = DEFAULT_DELAY_SECONDS,
        jitter: float = DEFAULT_JITTER_SECONDS,
    ) -> None:
        """初始化防抖器。

        Args:
            delay: 基础等待时长（秒）。
            jitter: 在基础时长上叠加的随机抖动上限（秒）。
        """

        self.delay = delay
        self.jitter = jitter
        # session_key -> 待处理的消息文本
        self._pending: DefaultDict[str, List[str]] = defaultdict(list)
        # session_key -> 该会话的处理循环
        self._loops: Dict[str, asyncio.Task[None]] = {}
        # session_key -> 聚合完成后要调用的回调
        self._callbacks: Dict[str, FlushCallback] = {}
        # session_key -> 到达计数，用于「突发合并」判定
        self._arrivals: Dict[str, int] = {}

    def next_wait(self) -> float:
        """返回本次的等待时长（含抖动）。

        Returns:
            float: 等待秒数。
        """

        return self.delay + random.uniform(0.0, self.jitter)

    def submit(
        self, session_key: str, text: str, callback: FlushCallback
    ) -> None:
        """提交一条入站消息。

        同一会话在等待窗口内的多条消息会被聚合；窗口结束后
        用最后一次提交的 ``callback`` 统一处理。

        Args:
            session_key: 会话标识。
            text: 消息文本。
            callback: 聚合完成后的处理回调。
        """

        if not session_key:
            return

        self._pending[session_key].append(text)
        self._callbacks[session_key] = callback

        existing = self._loops.get(session_key)
        if existing is not None and not existing.done():
            # 已有循环在跑，它会取走新追加的消息
            return

        self._loops[session_key] = asyncio.create_task(
            self._run_loop(session_key)
        )

    async def _run_loop(self, session_key: str) -> None:
        """等待静默后处理该会话累积的消息，直到没有新消息。

        Args:
            session_key: 会话标识。
        """

        while True:
            await asyncio.sleep(self.next_wait())

            items = self._pending.pop(session_key, [])
            if not items:
                break

            callback = self._callbacks.get(session_key)
            if callback is None:
                break

            # 回调内部异常不能让循环静默死掉，否则该会话
            # 之后的消息会永远堆在 _pending 里无人处理。
            await callback(items)

    def pending_count(self, session_key: str) -> int:
        """返回某会话当前待处理的消息数。

        Args:
            session_key: 会话标识。

        Returns:
            int: 待处理条数。
        """

        return len(self._pending.get(session_key, []))

    def note_arrival(self, session_key: str) -> int:
        """登记一条消息到达，返回本条的序号。

        配合 ``is_superseded`` 实现「突发合并」：调用方先取序号，
        睡完阅读延迟后检查自己是否已被更新的消息取代。
        这样一串连续消息只由最后一条作答，而不是逐条应答。

        Args:
            session_key: 会话标识。

        Returns:
            int: 本条消息的序号。
        """

        current = self._arrivals.get(session_key, 0) + 1
        self._arrivals[session_key] = current
        return current

    def is_superseded(self, session_key: str, token: int) -> bool:
        """判断持有 ``token`` 的消息是否已被更新的消息取代。

        Args:
            session_key: 会话标识。
            token: ``note_arrival`` 返回的序号。

        Returns:
            bool: 已被取代则为 True。
        """

        return self._arrivals.get(session_key, 0) > token

    async def shutdown(self) -> None:
        """取消所有处理循环，用于插件卸载。"""

        for task in self._loops.values():
            if not task.done():
                task.cancel()
        self._loops.clear()
        self._pending.clear()
        self._callbacks.clear()
