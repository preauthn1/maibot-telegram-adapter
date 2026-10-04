"""转换失败发生在追加前，不记录正文或异常原文。"""
from datetime import datetime, timezone
from unittest.mock import Mock
from src.chat.message_receive.message import SessionMessage
from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
from src.maisaka import runtime as module
from src.maisaka.context import history


def test_conversion_failure_does_not_commit_or_leak(monkeypatch):
    runtime = object.__new__(module.MaisakaHeartFlowChatting)
    runtime._chat_history = []
    monkeypatch.setattr(runtime, '_is_focus_mode_active_for_current_chat', lambda: False)
    image = Mock()
    monitor = Mock()
    monkeypatch.setattr(runtime, '_schedule_sent_image_recognition', image)
    monkeypatch.setattr(runtime, '_emit_monitor_message_sent', monitor)
    message = SessionMessage('private-id', datetime.now(timezone.utc), 'telegram')
    message.session_id = 'private-session'
    message.message_info = MessageInfo(UserInfo('private-user', 'private-name'))
    from src.common.data_models.message_component_data_model import MessageSequence
    message.raw_message = MessageSequence(components=[])
    def broken(*args, **kwargs):
        raise ValueError('PRIVATE_PAYLOAD_SENTINEL')
    monkeypatch.setattr(history, 'build_prefixed_message_sequence', broken)
    warning = Mock()
    monkeypatch.setattr(module.logger, 'warning', warning)
    assert runtime.append_sent_message_to_chat_history(message) is False
    assert runtime._chat_history == []
    image.assert_not_called()
    monitor.assert_not_called()
    warning.assert_called_once()
    assert warning.call_args.args[-1] == 'ValueError'
    assert 'PRIVATE_PAYLOAD_SENTINEL' not in str(warning.call_args)
    assert 'private-' not in str(warning.call_args)
