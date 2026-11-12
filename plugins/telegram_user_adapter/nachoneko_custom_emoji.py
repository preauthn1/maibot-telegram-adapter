"""Nachoneko 自定义 emoji 目录与出站后缀策略。"""
from __future__ import annotations

from typing import Any

import random
import re
import time

from telethon.tl.functions.messages import GetStickerSetRequest
from telethon.tl.types import DocumentAttributeCustomEmoji, InputStickerSetID, InputStickerSetShortName, MessageEntityCustomEmoji

from .fidelity.entities import utf16_len

PACK_SHORT_NAME = "HDNachoneko"
PACK_SET_ID = 238234019068642518


class NachonekoCustomEmoji:
    """校验指定 emoji 集合，并在发送边界原子预占一次后缀机会。"""

    def __init__(self) -> None:
        self._set_access_hash: int | None = None
        self._choices: tuple[tuple[str, int], ...] = ()
        self._last_sent: dict[str, float] = {}
        self._pending = False

    async def refresh(self, client: Any) -> None:
        result = await client(GetStickerSetRequest(
            stickerset=InputStickerSetShortName(PACK_SHORT_NAME), hash=0,
        ))
        meta = result.set
        if meta.short_name != PACK_SHORT_NAME or meta.id != PACK_SET_ID or not meta.access_hash:
            raise ValueError("Nachoneko emoji 集合身份不匹配")
        choices: list[tuple[str, int]] = []
        for document in result.documents:
            attribute = next(
                (item for item in document.attributes if isinstance(item, DocumentAttributeCustomEmoji)),
                None,
            )
            if attribute is None or not document.id or not document.file_reference:
                continue
            source = attribute.stickerset
            if not isinstance(source, InputStickerSetID):
                continue
            if (source.id, source.access_hash) != (meta.id, meta.access_hash):
                continue
            if not attribute.alt:
                continue
            choices.append((attribute.alt, document.id))
        if not choices:
            raise ValueError("Nachoneko emoji 集合没有可用自定义 emoji")
        self._set_access_hash = meta.access_hash
        self._choices = tuple(choices)

    @property
    def choice_count(self) -> int:
        return len(self._choices)

    def replace_trailing_laugh(self, text: str, chat_id: str, *, cooldown_seconds: float) -> tuple[str, Any, str] | None:
        """将正文末尾的模型文本笑声替换为原生自定义 emoji。"""
        match = re.search(r"(哈哈哈|哈哈)\s*$", text)
        if match is None or self._pending or not self._choices:
            return None
        now = time.monotonic()
        last = self._last_sent.get(chat_id)
        if last is not None and now - last < cooldown_seconds:
            return None
        self._pending = True
        alt, document_id = random.choice(self._choices)
        entity = MessageEntityCustomEmoji(offset=0, length=utf16_len(alt), document_id=document_id)
        return text[:match.start()], entity, alt

    def reserve(self, chat_id: str, *, probability: float, cooldown_seconds: float) -> tuple[str, Any] | None:
        """同步完成概率、冷却和选择，await 前先占位避免并发重复。"""
        if self._pending or not self._choices or probability <= 0 or random.random() >= probability:
            return None
        now = time.monotonic()
        last = self._last_sent.get(chat_id)
        if last is not None and now - last < cooldown_seconds:
            return None
        self._pending = True
        alt, document_id = random.choice(self._choices)
        entity = MessageEntityCustomEmoji(
            offset=0, length=utf16_len(alt), document_id=document_id,
        )
        return alt, entity

    def finish(self, chat_id: str, *, success: bool) -> None:
        if success:
            now = time.monotonic()
            self._last_sent = {
                key: stamp for key, stamp in self._last_sent.items()
                if now - stamp < 3600
            }
            self._last_sent[chat_id] = now
        self._pending = False

    @property
    def available(self) -> bool:
        return bool(self._choices)
