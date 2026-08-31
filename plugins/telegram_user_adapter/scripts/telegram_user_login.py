"""Telegram 真人账号登录脚本。

用途：交互式登录一次，拿到 StringSession 填进 config.toml。

StringSession **等价于账号登录凭据**，泄露即等于账号被盗。
本脚本默认把它写到文件而不是打印到终端，避免被终端回滚记录、
截图或日志采集顺手带走。

用法：

    uv run python plugins/telegram_user_adapter/scripts/telegram_user_login.py

可用环境变量（不传则交互式询问）：

- ``TG_API_ID``    api_id
- ``TG_API_HASH``  api_hash
- ``TG_PHONE``     手机号（含国际区号，如 +8613800138000）
- ``TG_PROXY``     代理，如 ``socks5://127.0.0.1:1080``；直连可不填
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Tuple
from urllib.parse import urlparse

import asyncio
import getpass
import os
import sys

try:
    from telethon import TelegramClient
    from telethon.errors import (
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        SessionPasswordNeededError,
    )
    from telethon.sessions import StringSession
except ImportError:
    print("缺少依赖 telethon，请先安装：uv pip install telethon cryptg", file=sys.stderr)
    # from None：这是给人看的安装提示，原始 ImportError 的堆栈
    # 只会干扰阅读，不需要链在后面。
    raise SystemExit(1) from None


# 默认把 session 写到插件数据目录之外的独立文件，避免误提交。
_DEFAULT_OUTPUT = Path("data") / "telegram_user_session.txt"


def _parse_proxy(proxy_url: str) -> Optional[Tuple[Any, ...]]:
    """把代理 URL 解析成 Telethon 需要的元组。

    Args:
        proxy_url: 形如 ``socks5://user:pass@host:port`` 的字符串。

    Returns:
        Optional[Tuple[Any, ...]]: Telethon 代理元组；未配置时返回 ``None``。

    Raises:
        ValueError: 代理协议不受支持或缺少主机端口。
    """

    if not proxy_url.strip():
        return None

    parsed = urlparse(proxy_url.strip())
    scheme = parsed.scheme.lower()
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"代理地址缺少主机或端口: {proxy_url}")

    import socks  # type: ignore[import-not-found]

    scheme_map = {
        "socks5": socks.SOCKS5,
        "socks5h": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
        "https": socks.HTTP,
    }
    if scheme not in scheme_map:
        raise ValueError(f"不支持的代理协议: {scheme}")

    proxy: Tuple[Any, ...] = (scheme_map[scheme], parsed.hostname, parsed.port)
    if parsed.username and parsed.password:
        proxy += (True, parsed.username, parsed.password)
    return proxy


def _prompt(label: str, env_key: str, *, secret: bool = False) -> str:
    """读取一个参数，优先取环境变量。

    Args:
        label: 交互提示文案。
        env_key: 环境变量名。
        secret: 是否按密码方式读取（不回显）。

    Returns:
        str: 读取到的值。
    """

    value = os.environ.get(env_key, "").strip()
    if value:
        return value
    if secret:
        return getpass.getpass(f"{label}: ").strip()
    return input(f"{label}: ").strip()


async def main() -> int:
    """执行交互式登录并保存 StringSession。

    Returns:
        int: 进程退出码。
    """

    raw_api_id = _prompt("api_id", "TG_API_ID")
    try:
        api_id = int(raw_api_id)
    except ValueError:
        print(f"api_id 必须是数字，收到: {raw_api_id!r}", file=sys.stderr)
        return 1

    api_hash = _prompt("api_hash", "TG_API_HASH")
    if not api_hash:
        print("api_hash 不能为空。", file=sys.stderr)
        return 1

    phone = _prompt("手机号（含国际区号，如 +8613800138000）", "TG_PHONE")
    if not phone:
        print("手机号不能为空。", file=sys.stderr)
        return 1
    if not phone.startswith("+"):
        print(
            f"手机号必须含国际区号并以 + 开头，收到: {phone!r}\n"
            "例如中国大陆号码写成 +8613800138000",
            file=sys.stderr,
        )
        return 1

    try:
        proxy = _parse_proxy(os.environ.get("TG_PROXY", ""))
    except (ValueError, ImportError) as exc:
        print(f"代理配置无效: {exc}", file=sys.stderr)
        return 1

    client = TelegramClient(
        StringSession(),
        api_id,
        api_hash,
        proxy=proxy,
        device_model="iPhone 15 Pro",
        system_version="iOS 17.4",
        app_version="10.9.1",
    )

    await client.connect()
    try:
        if await client.is_user_authorized():
            print("该 session 已经是登录状态。")
        else:
            await client.send_code_request(phone)
            print("验证码已发送，请查收 Telegram 应用内消息或短信。")

            code = input("验证码: ").strip()
            try:
                await client.sign_in(phone=phone, code=code)
            except SessionPasswordNeededError:
                # 开启了两步验证，需要额外输入密码。
                password = getpass.getpass("两步验证密码: ")
                await client.sign_in(password=password)
            except PhoneCodeInvalidError:
                print("验证码错误。", file=sys.stderr)
                return 1
            except PhoneCodeExpiredError:
                print("验证码已过期，请重新运行本脚本。", file=sys.stderr)
                return 1

        me = await client.get_me()
        session_string = client.session.save()
    finally:
        await client.disconnect()

    output_path = Path(os.environ.get("TG_SESSION_OUT", str(_DEFAULT_OUTPUT)))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(session_string, encoding="utf-8")
    output_path.chmod(0o600)

    print()
    print(f"登录成功：id={me.id} username={me.username} phone={me.phone}")
    print(f"StringSession 已写入：{output_path}（权限 600）")
    print()
    print("接下来把它填进 plugins/telegram_user_adapter/config.toml：")
    print()
    print("  [plugin]")
    print("  enabled = true")
    print()
    print("  [telegram_account]")
    print(f"  api_id = {api_id}")
    print('  api_hash = "……"')
    print(f'  session_string = "<{output_path} 的内容>"')
    print()
    print("⚠️  StringSession 等价于账号登录凭据，不要提交到 git、不要发给别人。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
