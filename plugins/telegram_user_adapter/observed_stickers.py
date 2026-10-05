# SPDX-License-Identifier: GPL-3.0-or-later
# Modified 2026-10-06; see STICKER_RAW_NOTICES.md.
"""当前聊天/话题内的有界贴纸目录；引用与凭据只存内存。"""
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import asyncio
import secrets
import time

from .utils import parse_topic_group_id


@dataclass
class SeenSticker:
    source: Any
    document: Any
    emoji: str
    description: str
    expires: float


class ObservedStickers:
    def __init__(self) -> None:
        self.routes = OrderedDict()

    @staticmethod
    def permitted(message: Any, scope: str) -> bool:
        from .native_tools import in_scope
        base, topic = parse_topic_group_id(scope)
        media = getattr(message, "media", None)
        return (in_scope(message, int(base), topic)
                and bool(getattr(message, "sticker", None))
                and not getattr(message, "noforwards", False)
                and not getattr(getattr(message, "chat", None), "noforwards", False)
                and not getattr(message, "ttl_period", None)
                and not getattr(media, "ttl_seconds", None))

    def observe(self, scope: str, message: Any, description: str = "") -> None:
        if not self.permitted(message, scope):
            return
        doc = getattr(message, "document", None)
        if doc is None or not doc.access_hash or not doc.file_reference:
            return
        emoji = next((str(a.alt)[:32] for a in doc.attributes
                      if type(a).__name__ == "DocumentAttributeSticker"), "")
        bucket = self.routes.setdefault(scope, OrderedDict())
        # 描述只能来自已有识别结果；缺失时不根据 emoji 猜图义。
        description = description[:500] if isinstance(description, str) else ""
        for token, item in list(bucket.items()):
            if item.expires <= time.monotonic() or item.source.id == message.id:
                del bucket[token]
        bucket[secrets.token_urlsafe(24)] = SeenSticker(message, doc, emoji, description, time.monotonic()+3600)
        while len(bucket) > 64:
            bucket.popitem(last=False)
        self.routes.move_to_end(scope)
        while len(self.routes) > 256:
            self.routes.popitem(last=False)

    def resolve(self, scope: str, token: str) -> SeenSticker:
        item = self.routes.get(scope, {}).get(token) if isinstance(token, str) else None
        if item is None or item.expires <= time.monotonic() or not self.permitted(item.source, scope):
            raise ValueError("贴纸引用失效或不属于当前聊天/话题")
        return item

    def search(self, scope: str, query: str) -> list[dict[str, str]]:
        if not isinstance(query, str) or len(query) > 64:
            raise ValueError("查询过长")
        found = []
        for token in list(self.routes.get(scope, {})):
            try:
                item = self.resolve(scope, token)
            except ValueError:
                self.routes[scope].pop(token, None)
                continue
            if query.casefold() in (item.emoji + " " + item.description).casefold():
                found.append({"sticker_ref": token, "emoji": item.emoji,
                              "description": item.description, "description_source": "existing_recognition" if item.description else "unavailable"})
        return found[-20:]

    async def send(self, client: Any, entity: Any, scope: str, token: str, *, reply_to: Any = None) -> Any:
        from telethon.errors import FileReferenceExpiredError
        from telethon.utils import get_peer_id
        base, topic = parse_topic_group_id(scope)
        peer = get_peer_id(await asyncio.wait_for(client.get_input_entity(entity), 10))
        if peer != int(base) or (topic is not None and reply_to != topic):
            raise ValueError("贴纸目标与授权作用域不一致")
        item = self.resolve(scope, token)
        # 当前目标保护位变化也必须拒绝；不为正常发送刷新原始消息。
        target = await asyncio.wait_for(client.get_entity(entity), 10)
        if get_peer_id(target) != peer or getattr(target, "noforwards", False):
            raise ValueError("受保护会话不可复用贴纸")
        async def deliver() -> Any:
            self.resolve(scope, token)
            sent = await asyncio.wait_for(client.send_file(entity, item.document, reply_to=reply_to), 30)
            if sent is None or type(sent.id) is not int or sent.id <= 0 or sent.chat_id != peer:
                raise ValueError("贴纸投递未确认；勿自动重试")
            return sent
        try:
            return await deliver()
        except FileReferenceExpiredError:
            fresh = await asyncio.wait_for(client.get_messages(peer, ids=item.source.id), 10)
            self.resolve(scope, token)
            if (fresh is None or fresh.id != item.source.id or not self.permitted(fresh, scope)
                    or fresh.document.id != item.document.id
                    or fresh.document.access_hash != item.document.access_hash):
                raise ValueError("贴纸原始来源已改变或不可访问")
            item.source, item.document = fresh, fresh.document
            return await deliver()
