"""URL 主机解析不能靠冒号截断；全部离线。"""
import pytest
from plugins.telegram_user_adapter.command_url_guard import _hostname_of


@pytest.mark.parametrize('url, host', [
    ('https://[2001:db8::1]:8443/a', '2001:db8::1'),
    ('https://user:password@example.com:8443/a', 'example.com'),
    ('example.com:8080/a', 'example.com'),
    ('HTTPS://EXAMPLE.COM/a', 'example.com'),
    ('https://[broken/a', ''),
])
def test_hostname_parsing(url, host):
    assert _hostname_of(url) == host
