"""损坏地址不应静默验证成功或回显敏感原文。"""
from unittest.mock import Mock
import socket
import pytest
from plugins.telegram_user_adapter.command_url_guard import verify_urls_resolvable


@pytest.mark.parametrize('url', ['', 'https:///path?token=SECRET', 'https://user:SECRET@[broken/a'])
def test_invalid_url_rejected_without_resolution(monkeypatch, url):
    resolver = Mock()
    monkeypatch.setattr(socket, 'getaddrinfo', resolver)
    result = verify_urls_resolvable([url])
    assert result == (False, ['<invalid-url>'])
    assert 'SECRET' not in str(result)
    resolver.assert_not_called()
