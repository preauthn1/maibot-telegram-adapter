"""真实出站 URL 拒绝路径不在告警中回显敏感命令。"""
import asyncio
from unittest.mock import Mock
from test_low_information_outbound import make_codec, send
from telegram_user_adapter.codecs import outbound


def test_url_rejection_avoids_command_disclosure(monkeypatch):
    codec, sender = make_codec()
    logger = Mock()
    codec._logger = logger
    monkeypatch.setattr(outbound, 'verify_urls_resolvable', lambda urls: (False, ['example.invalid']))
    result = asyncio.run(send(codec, 'curl https://example.invalid/a?token=PRIVATE_SENTINEL'))
    assert result is None
    assert sender.sent == []
    logger.error.assert_called_once_with('命令 URL 检查未通过，已拦截；失败项数=%d', 1)
    assert 'PRIVATE_SENTINEL' not in str(logger.mock_calls)
