"""出站英文统一小写：账号主人的打字习惯是英文全小写（tun、vpn、https）。

只改 ASCII 大写字母；以下片段原样保留，避免改坏可复制内容：
- 含 shell 命令的整条消息（由 command_guard 判定）
- 反引号代码、URL、@用户名、文件路径
- 带 = 或 _ 的标识符（环境变量、配置键），以及字母数字混排的长串（哈希、ID、密钥样式）

运维可设 MAIBOT_TG_LOWERCASE=0 关闭。
"""
from __future__ import annotations

import os
import re

from .command_guard import has_command

_PROTECTED = re.compile(
    r"`[^`]*`"                                   # 行内代码
    r"|https?://\S+|www\.\S+"                    # 链接
    r"|@\w+"                                     # 用户名
    r"|(?:~|\.{1,2})?/[\w.\-/]+"                 # unix 路径
    r"|[A-Za-z]:\\\S*"                           # windows 路径
    r"|\b\w*[=_]\w*\b"                           # 配置键/环境变量
    r"|\b(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9]{8,}\b"  # 字母数字混排长串
)
_ASCII_LOWER = str.maketrans({chr(c): chr(c + 32) for c in range(ord("A"), ord("Z") + 1)})


def enabled() -> bool:
    return os.environ.get("MAIBOT_TG_LOWERCASE", "1").strip().lower() not in {"0", "false", "off", "no"}


def to_lowercase_style(text: str) -> str:
    """返回英文小写后的文本；不需要改动时原样返回。"""
    if not text or not enabled() or not any("A" <= ch <= "Z" for ch in text):
        return text
    if has_command(text):
        return text
    parts = []
    position = 0
    for match in _PROTECTED.finditer(text):
        parts.append(text[position:match.start()].translate(_ASCII_LOWER))
        parts.append(match.group(0))
        position = match.end()
    parts.append(text[position:].translate(_ASCII_LOWER))
    return "".join(parts)
