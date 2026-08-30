"""Telegram 出站引用降频测试。

条条带引用是机器人最明显的特征之一，因此引用改为按概率保留。
但话题群的 ``reply_to`` 是路由所需（丢了消息会落到 General），
必须验证降频只影响\"引用\"而不影响\"路由\"。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.codecs.outbound import TelegramUserOutboundCodec  # noqa: E402


class _StubMessage:
    """Telethon 返回的已发送消息桩。"""

    def __init__(self, msg_id: int = 1) -> None:
        self.id = msg_id


class _RecordingCodec(TelegramUserOutboundCodec):
    """记录每次发送时实际使用的 reply_to，用于断言。"""

    def __init__(self, force_quote: bool) -> None:
        super().__init__(None, _StubLogger())
        self._force_quote = force_quote
        self.used_reply_to: List[Optional[int]] = []

    def _should_quote(self) -> bool:
        # 用确定值替代随机，让测试稳定。
        return self._force_quote

    async def _resolve_entity(self, chat_id: str) -> Any:
        return object()

    async def _send_segment(self, entity: Any, seg: Dict[str, Any], reply_to: Optional[int]) -> Any:
        self.used_reply_to.append(reply_to)
        return _StubMessage()


class _StubLogger:
    def info(self, *a: Any, **k: Any) -> None: ...
    def debug(self, *a: Any, **k: Any) -> None: ...
    def warning(self, *a: Any, **k: Any) -> None: ...
    def error(self, *a: Any, **k: Any) -> None: ...


def _build_message(group_id: str, reply_message_id: Optional[int]) -> Dict[str, Any]:
    """构造一条出站消息字典。"""

    additional: Dict[str, Any] = {"platform_io_target_group_id": group_id}
    if reply_message_id is not None:
        additional["reply_message_id"] = reply_message_id
    return {
        "message_info": {"additional_config": additional},
        "raw_message": [{"type": "text", "data": "测试内容"}],
    }


@pytest.mark.asyncio
async def test_quote_kept_when_probability_hits() -> None:
    """概率命中时保留引用。"""

    codec = _RecordingCodec(force_quote=True)
    await codec.send_outbound_message(_build_message("-1009000000004", 555), {})

    assert codec.used_reply_to == [555]


@pytest.mark.asyncio
async def test_quote_dropped_when_probability_misses() -> None:
    """概率未命中时丢掉引用，普通群直接不带 reply_to。"""

    codec = _RecordingCodec(force_quote=False)
    await codec.send_outbound_message(_build_message("-1009000000004", 555), {})

    assert codec.used_reply_to == [None]


@pytest.mark.asyncio
async def test_topic_routing_survives_quote_drop() -> None:
    """关键：话题群丢掉引用后必须回落到 topic 根 ID，否则消息会跑到 General。"""

    codec = _RecordingCodec(force_quote=False)
    topic_group = "-1009000000004::tg-topic::mt=77"
    await codec.send_outbound_message(_build_message(topic_group, 555), {})

    # 引用被丢弃，但 topic 根 ID 必须补上
    assert codec.used_reply_to == [77]


@pytest.mark.asyncio
async def test_topic_quote_kept_when_probability_hits() -> None:
    """话题群概率命中时，引用优先于 topic 根 ID（引用本身就在该话题内）。"""

    codec = _RecordingCodec(force_quote=True)
    topic_group = "-1009000000004::tg-topic::mt=77"
    await codec.send_outbound_message(_build_message(topic_group, 555), {})

    assert codec.used_reply_to == [555]


@pytest.mark.asyncio
async def test_topic_routing_without_any_quote() -> None:
    """话题群本来就没有引用时，照常使用 topic 根 ID。"""

    codec = _RecordingCodec(force_quote=False)
    topic_group = "-1009000000004::tg-topic::mt=88"
    await codec.send_outbound_message(_build_message(topic_group, None), {})

    assert codec.used_reply_to == [88]


def test_quote_probability_distribution() -> None:
    """引用概率应当接近配置值。"""

    import random

    codec = TelegramUserOutboundCodec(None, _StubLogger())
    codec.set_behavior(
        simulate_typing=False,
        typing_cps=6.0,
        min_think_delay=0.0,
        max_typing_delay=1.0,
        quote_probability=0.15,
    )
    random.seed(20260831)
    hits = sum(codec._should_quote() for _ in range(5000))
    assert 0.12 <= hits / 5000 <= 0.18


def test_quote_probability_bounds() -> None:
    """概率取 0 与 1 时行为必须确定。"""

    codec = TelegramUserOutboundCodec(None, _StubLogger())

    codec.set_behavior(
        simulate_typing=False, typing_cps=6.0, min_think_delay=0.0,
        max_typing_delay=1.0, quote_probability=0.0,
    )
    assert not any(codec._should_quote() for _ in range(200))

    codec.set_behavior(
        simulate_typing=False, typing_cps=6.0, min_think_delay=0.0,
        max_typing_delay=1.0, quote_probability=1.0,
    )
    assert all(codec._should_quote() for _ in range(200))


def test_config_normalizes_out_of_range_probability() -> None:
    """配置里写了越界值要被规范化，不能直接透传。"""

    from telegram_user_adapter.config import TelegramUserBehaviorConfig

    assert TelegramUserBehaviorConfig(quote_probability=5.0).quote_probability == 1.0
    assert TelegramUserBehaviorConfig(quote_probability=-1.0).quote_probability == 0.0
    assert TelegramUserBehaviorConfig(quote_probability="abc").quote_probability == 0.15


@pytest.mark.asyncio
async def test_topic_routing_not_counted_as_quote() -> None:
    """话题群为路由带的 reply_to 不该被记成\"引用\"，否则统计会失真。"""

    codec = _RecordingCodec(force_quote=False)
    topic_group = "-1009000000004::tg-topic::mt=77"
    await codec.send_outbound_message(_build_message(topic_group, 555), {})

    assert codec.used_reply_to == [77]
    # 路由用的 reply_to 不算引用
    assert codec.last_reply_is_quote is False


@pytest.mark.asyncio
async def test_real_quote_is_counted() -> None:
    """真正的引用要被记录，才能统计引用率。"""

    codec = _RecordingCodec(force_quote=True)
    await codec.send_outbound_message(_build_message("-1009000000004", 555), {})

    assert codec.last_reply_is_quote is True


@pytest.mark.asyncio
async def test_no_reply_is_not_quote() -> None:
    """完全不带 reply_to 时自然不算引用。"""

    codec = _RecordingCodec(force_quote=False)
    await codec.send_outbound_message(_build_message("-1009000000004", 555), {})

    assert codec.used_reply_to == [None]
    assert codec.last_reply_is_quote is False
