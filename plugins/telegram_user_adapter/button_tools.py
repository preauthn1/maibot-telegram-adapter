# SPDX-License-Identifier: GPL-3.0-or-later
# Modified 2026-10-06; see PORT-NOTICES.md.
"""Bot 内联按钮票据：会话/消息绑定、过期、一次消费；不执行任意回调代码。"""
from __future__ import annotations
from collections import OrderedDict
from typing import Any
import secrets
import time
from urllib.parse import urlsplit


def checked_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise ValueError("按钮 URL 无效")
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("按钮只允许不含凭据的 HTTPS 链接")
        if parsed.port not in (None, 443):
            raise ValueError("按钮链接端口无效")
    except ValueError:
        raise ValueError("按钮 URL 无效") from None
    return value


class ButtonTickets:
    def __init__(self) -> None:
        self.pending = OrderedDict()

    def prepare(self, scope: str, rows: Any) -> list[list[dict[str, str]]]:
        if not isinstance(rows, list) or not 1 <= len(rows) <= 4:
            raise ValueError("按钮必须为 1–4 行")
        checked = []
        for row in rows:
            if not isinstance(row, list) or not 1 <= len(row) <= 4:
                raise ValueError("每行必须为 1–4 个按钮")
            result = []
            for button in row:
                if not isinstance(button, dict) or set(button) not in ({"text", "data"}, {"text", "url"}):
                    raise ValueError("按钮必须为 text/data 或 text/url")
                if "url" in button:
                    checked_url(button["url"])
                if any(not isinstance(button[k], str) or not 1 <= len(button[k].encode()) <= 64 for k in button if k != "url"):
                    raise ValueError("按钮文字和回调内容必须为 1–64 字节")
                result.append(dict(button))
            checked.append(result)
        now = time.monotonic()
        for row in checked:
            for button in row:
                if "url" in button:
                    continue
                token = "mbc:" + secrets.token_urlsafe(18)
                self.pending[token] = (scope, button["text"], button["data"], now + 600, None)
                button["data"] = token
        while len(self.pending) > 1024:
            self.pending.popitem(last=False)
        return checked

    def bind(self, rows: Any, message_id: str) -> None:
        for row in rows:
            for button in row:
                if "url" in button:
                    continue
                token = button["data"]
                if token in self.pending:
                    scope,label,data,expiry,_ = self.pending[token]
                    self.pending[token] = (scope,label,data,expiry,str(message_id))

    def consume(self, token: str, scope: str, message_id: str) -> tuple[str, str] | None:
        entry = self.pending.get(token)
        if entry is None:
            return None
        owner,label,data,expiry,mid = entry
        if owner != scope or mid != str(message_id) or expiry < time.monotonic():
            return None
        self.pending.pop(token)
        return label,data


def telethon_buttons(rows: Any) -> Any:
    from telethon import Button
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4:
        raise ValueError("按钮结构无效")
    result = []
    for row in rows:
        if not isinstance(row, list) or not 1 <= len(row) <= 4:
            raise ValueError("按钮结构无效")
        out = []
        for button in row:
            if isinstance(button, dict) and set(button) == {"text", "url"}:
                if not isinstance(button["text"], str) or not 1 <= len(button["text"].encode()) <= 64:
                    raise ValueError("按钮文字长度无效")
                out.append(Button.url(button["text"], checked_url(button["url"])))
                continue
            if set(button) != {"text", "data"} or not button["data"].startswith("mbc:"):
                raise ValueError("非本插件按钮票据")
            if not 1 <= len(button["text"].encode()) <= 64 or not 1 <= len(button["data"].encode()) <= 64:
                raise ValueError("按钮长度无效")
            out.append(Button.inline(button["text"], button["data"].encode()))
        result.append(out)
    return result
