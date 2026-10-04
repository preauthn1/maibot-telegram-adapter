"""真实发送目标组件→host序列化→codec；只能在断网隔离回归中运行。"""
from types import SimpleNamespace

import asyncio
import logging

import pytest

from src.plugin_runtime.host.message_utils import PluginMessageUtils
from src.services.send_service import _build_reply_component
from test_low_information_outbound import make_codec


def test_real_host_target_preview_reaches_codec():
    async def scenario():
        codec, sender = make_codec()
        codec._quote_probability = 1.0
        for number in range(3):
            target_id = str(900 + number)
            target = SimpleNamespace(message_id=target_id,
                processed_plain_text=f"请确认方案{number}，只回复‘收到’。",
                message_info=SimpleNamespace(user_info=SimpleNamespace(
                    user_id="synthetic-user", user_nickname="合成用户", user_cardname="")))
            component = _build_reply_component(target_id, target)
            wire = PluginMessageUtils._component_to_dict(component, include_binary_data=False)
            assert wire["data"]["target_message_content"] == target.processed_plain_text
            result = await codec.send_outbound_message({
                "message_info": {"group_info": {"group_id": "123"}},
                "raw_message": [wire, {"type": "text", "data": "收到"}]},
                {})
            assert result["success"] is True
        assert sender.sent == ["收到", "收到", "收到"]
    asyncio.run(scenario())


def test_mismatched_host_target_has_no_ack_authority():
    target = SimpleNamespace(message_id="wrong", processed_plain_text="只回复收到。")
    component = _build_reply_component("901", target)
    wire = PluginMessageUtils._component_to_dict(component, include_binary_data=False)
    assert wire["data"]["target_message_id"] == "901"
    assert not wire["data"]["target_message_content"]


def test_quiet_queue_rejects_ack_before_codec(monkeypatch):
    from telegram_user_adapter.send_queue import QuietHoursError, SendQueue

    async def scenario():
        codec, sender = make_codec()
        queue = SendQueue(logging.getLogger(__name__), enable_quiet_hours=True)
        monkeypatch.setattr(queue, "in_quiet_hours", lambda: True)
        queue.start()
        try:
            async def action():
                return await codec.send_outbound_message({
                    "message_info": {"group_info": {"group_id": "123"}},
                    "raw_message": [{"type": "reply", "data": {
                        "target_message_id": "901", "target_message_content": "只回复收到。",
                        "target_message_sender_id": "peer"}}, {"type": "text", "data": "收到"}]}, {})
            with pytest.raises(QuietHoursError):
                await queue.submit(action)
            assert sender.sent == []
        finally:
            await queue.stop()
    asyncio.run(scenario())
