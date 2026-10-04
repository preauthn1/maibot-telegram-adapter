"""临时 DNS 故障不等于名称不存在；无真实网络请求。"""
import socket
import pytest
from plugins.telegram_user_adapter.command_url_guard import verify_urls_resolvable


@pytest.mark.parametrize('code, expected', [
    (socket.EAI_AGAIN, (True, [])),
    (socket.EAI_FAIL, (True, [])),
    (socket.EAI_NONAME, (False, ['example.invalid'])),
])
def test_resolver_errors_are_distinguished(monkeypatch, code, expected):
    def fail(*args, **kwargs):
        raise socket.gaierror(code, 'synthetic resolver failure')
    monkeypatch.setattr(socket, 'getaddrinfo', fail)
    assert verify_urls_resolvable(['https://example.invalid']) == expected
