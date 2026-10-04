"""发送编排只提交成功返回的最终对象；平台 I/O 和历史存储均隔离。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.services import send_service as module


@pytest.mark.parametrize('outcome', ['success', 'none', 'error'])
def test_history_commit_follows_platform_result(monkeypatch, outcome):
    original = SimpleNamespace(message_id='synthetic-original')
    final = SimpleNamespace(message_id='synthetic-final')
    io = AsyncMock(return_value=final if outcome == 'success' else None)
    if outcome == 'error':
        io.side_effect = OSError('synthetic failure')
    commit = Mock()
    monkeypatch.setattr(module, '_send_via_platform_io', io)
    monkeypatch.setattr(module, '_sync_sent_message_to_maisaka_history', commit)
    call = module.send_session_message_with_message(
        original, sync_to_maisaka_history=True, maisaka_source_kind='guided_reply',
        storage_message=False, show_log=False)
    if outcome == 'error':
        with pytest.raises(OSError):
            asyncio.run(call)
    else:
        result = asyncio.run(call)
        assert result is (final if outcome == 'success' else None)
    if outcome == 'success':
        commit.assert_called_once_with(final, source_kind='guided_reply')
    else:
        commit.assert_not_called()
    io.assert_awaited_once()
