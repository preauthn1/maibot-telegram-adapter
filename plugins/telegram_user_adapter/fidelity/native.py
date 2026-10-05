# SPDX-License-Identifier: GPL-3.0-only
# Modified 2026-10-06; see PORT_NOTICES.md.
"""有界会话内原生媒体引用；不接受调用方提供的 Telegram 对象。"""
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional
import asyncio
import secrets
import time


@dataclass
class Reference:
    peer: int
    message_id: int
    media_id: int
    kind: str
    media: Any
    expires: float


class NativeReferences:
    def __init__(self) -> None:
        self._refs = OrderedDict()

    def remember(self, message: Any) -> Optional[str]:
        if getattr(message, "noforwards", False) or getattr(message, "sticker", None):
            return None  # 不绕过受保护内容/批准贴纸目录
        if getattr(getattr(message, "media", None), "ttl_seconds", None):
            return None
        media = getattr(message, "photo", None) or getattr(message, "document", None)
        peer, mid = getattr(message, "chat_id", None), getattr(message, "id", None)
        if media is None or not isinstance(peer, int) or not isinstance(mid, int):
            return None
        if getattr(message, "photo", None):
            kind = "photo"
        elif getattr(message, "gif", None):
            kind = "animation"
        else:
            return None  # 不扩大文件、视频、语音的既有发送策略
        now = time.monotonic()
        for token, ref in list(self._refs.items()):
            if ref.expires <= now:
                del self._refs[token]
        token = secrets.token_urlsafe(24)
        self._refs[token] = Reference(peer, mid, media.id, kind, media, now + 3600)
        while len(self._refs) > 256:
            self._refs.popitem(last=False)
        return token

    def _resolve(self, token: str, peer: int) -> Reference:
        ref = self._refs.get(token)
        if ref is None or ref.expires <= time.monotonic() or ref.peer != peer:
            raise ValueError("原生媒体引用已失效或不属于当前会话")
        return ref

    async def send(self, client: Any, entity: Any, token: str, peer: int, *, reply_to: Any = None) -> Any:
        from telethon.errors import FileReferenceExpiredError, FileReferenceInvalidError
        ref = self._resolve(token, peer)
        try:
            return await asyncio.wait_for(client.send_file(entity, ref.media, reply_to=reply_to), 30)
        except (FileReferenceExpiredError, FileReferenceInvalidError):
            # 只允许一次精确源消息刷新；权限/网络错误不触发重新上传或任意查找。
            fresh = await asyncio.wait_for(client.get_messages(ref.peer, ids=ref.message_id), 10)
            self._resolve(token, peer)
            if fresh is None or fresh.id != ref.message_id or fresh.chat_id != ref.peer:
                raise ValueError("媒体源消息不匹配")
            if getattr(fresh, "noforwards", False) or getattr(fresh, "sticker", None):
                raise ValueError("媒体源现已受保护")
            if getattr(getattr(fresh, "media", None), "ttl_seconds", None):
                raise ValueError("限时媒体不可复用")
            media = getattr(fresh, "photo", None) if ref.kind == "photo" else getattr(fresh, "gif", None)
            if media is None or media.id != ref.media_id:
                raise ValueError("源媒体已被替换")
            ref.media = media
            return await asyncio.wait_for(client.send_file(entity, media, reply_to=reply_to), 30)
