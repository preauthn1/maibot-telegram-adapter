"""DNS 检查不得更改进程级 socket 设置。"""
from unittest.mock import Mock
import socket
from plugins.telegram_user_adapter.command_url_guard import verify_urls_resolvable


def test_dns_does_not_touch_socket_defaults(monkeypatch):
    setter = Mock(side_effect=AssertionError('global socket mutation'))
    getter = Mock(side_effect=AssertionError('global socket read'))
    monkeypatch.setattr(socket, 'setdefaulttimeout', setter)
    monkeypatch.setattr(socket, 'getdefaulttimeout', getter)
    resolver = Mock(return_value=[])
    monkeypatch.setattr(socket, 'getaddrinfo', resolver)
    assert verify_urls_resolvable(['https://example.com'], timeout=0.01) == (True, [])
    resolver.assert_called_once_with('example.com', None)
    setter.assert_not_called()
    getter.assert_not_called()
