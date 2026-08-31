"""出站单字噪音拦截测试。

主程序的中文错别字功能会在打错字后追加一条"纠正消息"，内容仅是
单个正确字（`src/chat/utils/utils.py` 的 typo_corrections 分支）。
真人不会孤零零发一个"什"，这种消息比错别字本身更可疑，
因此真人号插件必须在出站层拦截。
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.codecs.outbound import TelegramUserOutboundCodec  # noqa: E402


class _StubMessage:
    def __init__(self, msg_id: int = 1) -> None:
        self.id = msg_id


class _StubLogger:
    def info(self, *a: Any, **k: Any) -> None: ...
    def debug(self, *a: Any, **k: Any) -> None: ...
    def warning(self, *a: Any, **k: Any) -> None: ...
    def error(self, *a: Any, **k: Any) -> None: ...


class _RecordingCodec(TelegramUserOutboundCodec):
    """记录实际发送的文本。"""

    def __init__(self) -> None:
        super().__init__(None, _StubLogger())
        self.sent_texts: List[str] = []

    async def _resolve_entity(self, chat_id: str) -> Any:
        return object()

    async def _send_segment(
        self,
        entity: Any,
        chat_id: str,
        seg: Dict[str, Any],
        reply_to: Optional[int],
    ) -> Any:
        del entity, chat_id, reply_to
        if seg.get("type") == "text":
            self.sent_texts.append(str(seg.get("data", "")))
        return _StubMessage()


def _message(*texts: str) -> Dict[str, Any]:
    return {
        "message_info": {"additional_config": {"platform_io_target_group_id": "-1009000000004"}},
        "raw_message": [{"type": "text", "data": text} for text in texts],
    }


@pytest.mark.asyncio
async def test_single_char_correction_segment_is_dropped() -> None:
    """线上真实事故：错别字"神么"后跟单字"什"，单字必须被丢弃。"""

    codec = _RecordingCodec()

    await codec.send_outbound_message(_message("这是神么惊世发现", "什"), {})

    assert codec.sent_texts == ["这是神么惊世发现"]


@pytest.mark.asyncio
async def test_lone_single_char_message_is_dropped() -> None:
    """整条消息只有一个汉字时不应发送，避免纯噪音。"""

    codec = _RecordingCodec()

    result = await codec.send_outbound_message(_message("什"), {})

    assert codec.sent_texts == []
    assert result["success"] is False


@pytest.mark.asyncio
async def test_meaningful_short_replies_are_kept() -> None:
    """真人常用的短语气词必须保留，不能连带误杀。"""

    codec = _RecordingCodec()

    await codec.send_outbound_message(_message("哈哈", "确实", "好", "?", "6"), {})

    assert codec.sent_texts == ["哈哈", "确实", "好", "?", "6"]


@pytest.mark.asyncio
async def test_normal_multi_segment_send_unaffected() -> None:
    """正常多段回复不受影响。"""

    codec = _RecordingCodec()

    await codec.send_outbound_message(
        _message("猫能看到的是紫外线那边", "感受热倒是能靠脸上那圈须子皮肤啥的"),
        {},
    )

    assert len(codec.sent_texts) == 2
