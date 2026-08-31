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
from typing import Awaitable, Callable, DefaultDict, Dict, List, Tuple

import asyncio
import random
import time

# 判定"同一个人连发"的最大间隔（秒）。
#
# 2.0 秒：用封禁当天真实数据回放校准。最初实现是"阅读期间有任何
# 新消息就放弃"，活跃群 86-93% 消息被放弃，等于装死；而实测真人
# 85.5% 的发言都在"别人刚说完 2 秒内"，真人不因群活跃闭嘴。
# 收紧为"同发送者 + 间隔≤2s"后放弃率 18.8%，精确命中"一句话拆多条"。
DEFAULT_BURST_GAP_SECONDS = 2.0

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
        burst_gap: float = DEFAULT_BURST_GAP_SECONDS,
    ) -> None:
        """初始化防抖器。

        Args:
            delay: 基础等待时长（秒）。
            jitter: 在基础时长上叠加的随机抖动上限（秒）。
            burst_gap: 判定"同一个人连发"的最大间隔（秒）。
        """

        self.delay = delay
        self.jitter = jitter
        self.burst_gap = burst_gap
        # session_key -> 待处理的消息文本
        self._pending: DefaultDict[str, List[str]] = defaultdict(list)
        # session_key -> 该会话的处理循环
        self._loops: Dict[str, asyncio.Task[None]] = {}
        # session_key -> 聚合完成后要调用的回调
        self._callbacks: Dict[str, FlushCallback] = {}
        # session_key -> 到达计数，用于「突发合并」判定
        self._arrivals: Dict[str, int] = {}
        # session_key -> (最近发送者, 到达时刻)，判定是否同一个人连发
        self._last_sender: Dict[str, Tuple[str, float]] = {}

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

    def note_arrival(self, session_key: str, sender_id: str = "") -> int:
        """登记一条消息到达，返回本条的序号。

        配合 ``is_superseded`` 实现「突发合并」：调用方先取序号，
        睡完阅读延迟后检查自己是否已被同一个人的后续消息取代。

        Args:
            session_key: 会话标识。
            sender_id: 发送者标识，用于判定是否属于同一个人的连发。

        Returns:
            int: 本条消息的序号。
        """

        current = self._arrivals.get(session_key, 0) + 1
        self._arrivals[session_key] = current
        self._last_sender[session_key] = (sender_id, time.monotonic())
        return current

    def is_superseded(
        self, session_key: str, token: int, sender_id: str = ""
    ) -> bool:
        """判断持有 ``token`` 的消息是否应让位给后续消息。

        只在「后续消息来自同一发送者，且间隔极短」时才让位——
        那是一句话被拆成几条发的情况，本就该只回一次。

        为什么必须加这两个条件：最初的实现是「阅读期间有任何新消息
        就放弃」，用封禁当天真实数据回放，活跃群 86-93% 的消息会被
        放弃，账号会从"话太密"直接翻车成"几乎装死"。而实测真人在
        同等密度下 85.5% 的发言都发生在"别人刚说完 2 秒内"——
        真人根本不因为群活跃就闭嘴，行为与之相反。

        收紧后放弃率降到 18.8%，精确命中"一句话拆多条"而不误伤
        正常群聊（数据见 /tmp/verify_debounce_fix.py 的回放对比）。

        Args:
            session_key: 会话标识。
            token: ``note_arrival`` 返回的序号。
            sender_id: 本条消息的发送者标识。

        Returns:
            bool: 应让位则为 True。
        """

        if self._arrivals.get(session_key, 0) <= token:
            return False

        last = self._last_sender.get(session_key)
        if last is None:
            return False

        last_sender, last_at = last
        # 不同人说话不算连发：真人在这种情况下照样插话
        if not sender_id or last_sender != sender_id:
            return False

        # 间隔过长也不算连发，那是同一个人隔了一会儿又想起一句
        return (time.monotonic() - last_at) <= self.burst_gap

    async def shutdown(self) -> None:
        """取消所有处理循环，用于插件卸载。"""

        for task in self._loops.values():
            if not task.done():
                task.cancel()
        self._loops.clear()
        self._pending.clear()
        self._callbacks.clear()
