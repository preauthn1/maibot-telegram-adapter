"""历史失败独立告警，不把已发消息转换为发送失败。"""
import asyncio
from unittest.mock import Mock, AsyncMock
from types import SimpleNamespace
import pytest
from src.services import send_service
from src.chat.heart_flow.heartflow_manager import heartflow_manager
from src.chat.message_receive.message import SessionMessage
from datetime import datetime, timezone


@pytest.mark.parametrize('raises', [False, True])
def test_memory_failure_preserves_send_success(monkeypatch, raises):
    message = SessionMessage('synthetic', datetime.now(timezone.utc), 'telegram')
    message.session_id = 'synthetic-session'
    from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
    message.message_info = MessageInfo(UserInfo('synthetic-bot', '合成助手'))
    append = Mock(return_value=False)
    if raises:
        append.side_effect = RuntimeError('SECRET_TEST_CONTENT')
    monkeypatch.setattr(heartflow_manager, 'heartflow_chat_list', {
        message.session_id: SimpleNamespace(append_sent_message_to_chat_history=append)})
    io = AsyncMock(return_value=message)
    monkeypatch.setattr(send_service, '_send_via_platform_io', io)
    warning = Mock()
    monkeypatch.setattr(send_service.logger, 'warning', warning)
    result = asyncio.run(send_service.send_session_message_with_message(
        message, sync_to_maisaka_history=True, storage_message=False, show_log=False))
    assert result is message
    io.assert_awaited_once()
    append.assert_called_once()
    warning.assert_called_once()
    assert '消息已发送' in str(warning.call_args)
    assert 'SECRET_TEST_CONTENT' not in str(warning.call_args)
