"""发送后附属回调失败不得丢失已发送回执。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import asyncio
import logging
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.plugin import TelegramUserAdapterPlugin

@pytest.mark.parametrize('error', [OSError('synthetic-private'), ValueError('synthetic-private')])
def test_postsend_failure_preserves_receipt(error, caplog):
    plugin = object.__new__(TelegramUserAdapterPlugin)
    receipt = {'success':True,'external_message_id':'sent-1'}
    codec = SimpleNamespace(send_outbound_message=AsyncMock(return_value=receipt))
    async def submit(fn, **kwargs):
        return await fn()
    plugin._outbound_codec = codec
    plugin._send_queue = SimpleNamespace(submit=submit)
    plugin._resolve_outbound_chat_id = Mock(return_value='test')
    plugin._share_guard_for = Mock(return_value=SimpleNamespace(allows_send=lambda:True))
    plugin._is_consecutive_limited = Mock(return_value=False)
    plugin._consecutive_replies = {}
    plugin._last_spoke_at = {}
    plugin._resolve_priority = Mock(return_value=0)
    plugin._after_successful_send = AsyncMock(side_effect=error)
    plugin._logger = logging.getLogger('gateway-test')
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(plugin.handle_telegram_user_gateway({}))
    assert result == receipt
    codec.send_outbound_message.assert_awaited_once()
    assert plugin._consecutive_replies['test'] == 1
    assert 'synthetic-private' not in caplog.text
