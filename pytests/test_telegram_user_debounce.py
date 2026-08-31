"""入站防抖测试。

移植自 AEsirClaw 的 Debouncer 思路，解决我们现有的一个行为缺陷：
每条入站消息都单独进决策、单独回复。真人是「听完再说」——
群里连着来五句，人会读完再回一次，不会逐条应答。

2026-08-31 账号因用户举报被封（SpamBot 明确是人工审核确认），
逐条机械响应比发言总量更能解释「为什么被看出不是真人」。

对参考实现的两处修正：
1. 参考实现用 ``self._candidate.pop()`` 丢弃旧协程，未 await 的
   coroutine 会泄漏并触发 RuntimeWarning。这里改为存放消息数据
   而非协程，由调用方在聚合完成后自行处理。
2. 参考实现固定 delay，这里允许抖动，避免固定等待时长本身
   成为可识别特征。
"""

import asyncio
import time
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.debounce import InboundDebouncer  # noqa: E402


def test_single_message_passes_through() -> None:
    """单条消息应在等待后原样交回。"""

    async def scenario() -> list[str]:
        debouncer = InboundDebouncer(delay=0.05, jitter=0.0)
        collected: list[str] = []

        async def flush(items: list[str]) -> None:
            collected.extend(items)

        debouncer.submit("chat-a", "你好", flush)
        await asyncio.sleep(0.3)
        return collected

    assert asyncio.run(scenario()) == ["你好"]


def test_burst_merged_into_one_flush() -> None:
    """连续多条消息只触发一次处理——这是「听完再说」的核心。"""

    async def scenario() -> list[list[str]]:
        debouncer = InboundDebouncer(delay=0.15, jitter=0.0)
        flushes: list[list[str]] = []

        async def flush(items: list[str]) -> None:
            flushes.append(list(items))

        for text in ("第一句", "第二句", "第三句"):
            debouncer.submit("chat-a", text, flush)
            await asyncio.sleep(0.02)

        await asyncio.sleep(0.6)
        return flushes

    flushes = asyncio.run(scenario())

    assert len(flushes) == 1, f"应合并为 1 次处理，实际 {len(flushes)} 次"
    assert flushes[0] == ["第一句", "第二句", "第三句"]


def test_separate_chats_are_independent() -> None:
    """不同会话互不干扰。"""

    async def scenario() -> dict[str, list[str]]:
        debouncer = InboundDebouncer(delay=0.05, jitter=0.0)
        result: dict[str, list[str]] = {}

        def make_flush(key: str):
            async def flush(items: list[str]) -> None:
                result[key] = list(items)

            return flush

        debouncer.submit("chat-a", "A1", make_flush("chat-a"))
        debouncer.submit("chat-b", "B1", make_flush("chat-b"))
        await asyncio.sleep(0.4)
        return result

    result = asyncio.run(scenario())

    assert result == {"chat-a": ["A1"], "chat-b": ["B1"]}


def test_same_chat_serialized() -> None:
    """同一会话串行：前一批没处理完，新消息不会并发插入。"""

    async def scenario() -> list[str]:
        debouncer = InboundDebouncer(delay=0.05, jitter=0.0)
        order: list[str] = []

        async def flush(items: list[str]) -> None:
            order.append(f"start:{items[0]}")
            await asyncio.sleep(0.2)
            order.append(f"end:{items[0]}")

        debouncer.submit("chat-a", "批一", flush)
        await asyncio.sleep(0.15)
        debouncer.submit("chat-a", "批二", flush)
        await asyncio.sleep(0.8)
        return order

    order = asyncio.run(scenario())

    # 第一批必须完整结束后第二批才开始
    assert order.index("end:批一") < order.index("start:批二")


def test_no_pending_coroutine_leak() -> None:
    """不得因丢弃候选而泄漏未 await 的协程。

    参考实现用 pop() 直接丢协程，会触发
    "coroutine was never awaited" RuntimeWarning。
    我们存的是数据，不存在这个问题。
    """

    async def scenario() -> int:
        debouncer = InboundDebouncer(delay=0.05, jitter=0.0)
        count = 0

        async def flush(items: list[str]) -> None:
            nonlocal count
            count += len(items)

        for index in range(10):
            debouncer.submit("chat-a", f"m{index}", flush)
        await asyncio.sleep(0.5)
        return count

    # 10 条消息全部被处理，无丢失
    assert asyncio.run(scenario()) == 10


def test_jitter_varies_wait() -> None:
    """等待时长要有抖动——固定间隔本身就是自动化特征。"""

    debouncer = InboundDebouncer(delay=5.0, jitter=2.0)
    waits = {debouncer.next_wait() for _ in range(30)}

    assert len(waits) > 1, "等待时长完全固定"
    assert all(5.0 <= value <= 7.0 for value in waits)


def test_same_sender_burst_is_merged() -> None:
    """同一个人连发多条，只由最后一条作答——那是一句话被拆开了。"""

    debouncer = InboundDebouncer()

    first = debouncer.note_arrival("chat-a", "alice")
    second = debouncer.note_arrival("chat-a", "alice")
    third = debouncer.note_arrival("chat-a", "alice")

    assert debouncer.is_superseded("chat-a", first, "alice") is True
    assert debouncer.is_superseded("chat-a", second, "alice") is True
    assert debouncer.is_superseded("chat-a", third, "alice") is False


def test_different_sender_does_not_merge() -> None:
    """别人插话不该让我方放弃发言。

    这是修复的核心：最初实现「阅读期间有任何新消息就放弃」，
    用封禁当天真实数据回放，活跃群 86-93% 消息被放弃，等于装死。
    而实测真人 85.5% 的发言都在「别人刚说完 2 秒内」——
    真人不因群活跃闭嘴，行为与之相反。
    """

    debouncer = InboundDebouncer()

    token = debouncer.note_arrival("chat-a", "alice")
    debouncer.note_arrival("chat-a", "bob")

    assert debouncer.is_superseded("chat-a", token, "alice") is False


def test_stale_burst_not_merged() -> None:
    """同一个人隔太久又说话，不算连发。"""

    debouncer = InboundDebouncer(burst_gap=0.01)

    token = debouncer.note_arrival("chat-a", "alice")
    debouncer.note_arrival("chat-a", "alice")
    time.sleep(0.05)

    assert debouncer.is_superseded("chat-a", token, "alice") is False


def test_arrival_tokens_are_per_chat() -> None:
    """各会话的到达计数互不影响。"""

    debouncer = InboundDebouncer()

    token_a = debouncer.note_arrival("chat-a", "alice")
    debouncer.note_arrival("chat-b", "bob")
    debouncer.note_arrival("chat-b", "bob")

    assert debouncer.is_superseded("chat-a", token_a, "alice") is False
