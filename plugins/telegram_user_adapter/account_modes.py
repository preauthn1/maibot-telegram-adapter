"""账号模式边界；纯函数，不建立连接或读取任何实际凭据。"""
from pathlib import Path
from typing import Any


def validate_mode(mode: str, session_string: str, bot_token: str) -> str:
    if mode not in {'user', 'bot'}:
        raise ValueError('账号类型必须为 user 或 bot')
    if mode == 'user' and bot_token:
        raise ValueError('用户账号模式不得配置 Bot Token')
    if mode == 'bot':
        if session_string:
            raise ValueError('Bot 模式不得复用用户 StringSession')
        prefix, sep, secret = bot_token.partition(':')
        if not sep or not prefix.isascii() or not prefix.isdigit() or not secret:
            raise ValueError('Bot Token 格式无效')
    return mode


def session_for_mode(path: Path, mode: str) -> Path:
    if mode == 'user':
        return path
    if mode != 'bot':
        raise ValueError('未知账号模式')
    return path.with_name(path.stem + '.bot' + path.suffix)


def validate_identity(me: Any, mode: str, bot_token: str = '') -> None:
    if me is None or bool(me.bot) != (mode == 'bot'):
        raise ValueError('已授权会话与配置账号类型不一致，拒绝监听')
    if mode == 'bot':
        prefix, sep, _ = bot_token.partition(':')
        if not sep or not prefix.isdigit() or int(prefix) != me.id:
            raise ValueError('已授权 Bot 身份与配置不一致，拒绝监听')
