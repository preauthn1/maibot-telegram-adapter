"""Telegram 真人账号登录助手。

交互式完成一次 MTProto 登录，并输出可直接填入插件配置的 StringSession。

用法::

    uv run python scripts/telegram_user_login.py

或者直接用环境变量跑非交互流程::

    TG_API_ID=123456 TG_API_HASH=xxx TG_PHONE=+8613800000000 \
        uv run python scripts/telegram_user_login.py
"""

from __future__ import annotations

from typing import Optional

import asyncio
import os
import sys


def _prompt(label: str, env_key: str, *, secret: bool = False) -> str:
    """读取一个配置值，优先取环境变量。

    Args:
        label: 交互提示文案。
        env_key: 对应的环境变量名。
        secret: 是否按密码方式读取。

    Returns:
        str: 用户输入或环境变量值。
    """

    env_value = os.environ.get(env_key, "").strip()
    if env_value:
        return env_value
    if secret:
        import getpass

        return getpass.getpass(f"{label}: ").strip()
    return input(f"{label}: ").strip()


def _build_proxy(proxy_url: str) -> Optional[tuple]:
    """把代理 URL 转换为 Telethon proxy 元组。

    Args:
        proxy_url: 代理地址。

    Returns:
        Optional[tuple]: Telethon proxy 参数；无代理时返回 ``None``。

    Raises:
        ValueError: 协议不受支持或地址不完整时抛出。
    """

    normalized = (proxy_url or "").strip()
    if not normalized:
        return None

    import socks
    from urllib.parse import urlparse

    parsed = urlparse(normalized)
    scheme = (parsed.scheme or "").lower()
    proxy_types = {
        "socks5": socks.SOCKS5,
        "socks5h": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
        "https": socks.HTTP,
    }
    proxy_type = proxy_types.get(scheme)
    if proxy_type is None:
        raise ValueError(f"不支持的代理协议: {scheme or normalized}")
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"代理地址缺少主机或端口: {normalized}")
    if parsed.username:
        return (proxy_type, parsed.hostname, parsed.port, True, parsed.username, parsed.password or "")
    return (proxy_type, parsed.hostname, parsed.port)


async def main() -> int:
    """执行交互式登录流程。

    Returns:
        int: 进程退出码。
    """

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("缺少依赖 telethon。请先执行: uv pip install telethon cryptg")
        return 1

    api_id_raw = _prompt("Telegram API ID", "TG_API_ID")
    try:
        api_id = int(api_id_raw)
    except ValueError:
        print(f"API ID 必须是整数，收到: {api_id_raw}")
        return 1

    api_hash = _prompt("Telegram API Hash", "TG_API_HASH", secret=True)
    phone = _prompt("手机号（含国际区号，如 +8613800000000）", "TG_PHONE")
    proxy_url = os.environ.get("TG_PROXY", "").strip()

    device_model = os.environ.get("TG_DEVICE_MODEL", "iPhone 15 Pro")
    system_version = os.environ.get("TG_SYSTEM_VERSION", "iOS 17.4")
    app_version = os.environ.get("TG_APP_VERSION", "10.9.1")

    client = TelegramClient(
        StringSession(),
        api_id,
        api_hash,
        proxy=_build_proxy(proxy_url),
        device_model=device_model,
        system_version=system_version,
        app_version=app_version,
    )

    await client.connect()
    if not await client.is_user_authorized():
        await client.send_code_request(phone)
        code = _prompt("Telegram 发送的验证码", "TG_CODE")
        try:
            await client.sign_in(phone, code)
        except Exception as exc:
            if "password" not in str(exc).lower() and "2fa" not in str(exc).lower():
                raise
            password = _prompt("两步验证密码", "TG_PASSWORD", secret=True)
            await client.sign_in(password=password)

    me = await client.get_me()
    session_string = client.session.save()
    await client.disconnect()

    print("\n登录成功：")
    print(f"  id       = {me.id}")
    print(f"  username = {me.username}")
    print(f"  name     = {me.first_name or ''} {me.last_name or ''}".rstrip())
    print("\n把下面这行填到插件配置的 telegram_account.session_string：\n")
    print(session_string)
    print("\n注意：StringSession 等价于账号登录凭据，请勿泄露。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
