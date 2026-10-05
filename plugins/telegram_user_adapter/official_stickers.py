"""只复用指定官方 Telegram 套装的原生 Document，不下载、不重传。

来源由短名 RPC 确认，emoji 语义仅来自服务端 StickerPack；没有精确匹配
就不发。调用方必须继续走原有网关、队列及预算，不能把此模块当发送工具。
"""
from __future__ import annotations

from typing import Any

import asyncio
import os
import time

from .unlimited_mode import is_unlimited

PACK_SHORT_NAME = "UtyaDuck"
# 用户批准的公共套装 ID（不是账号或会话标识）。新增套装必须代码评审注册。
PACK_SET_ID = 773947703670341644
# 只自动选择常用、明确的情绪，不将 🦆/工具/物品标签当成情绪。
REACTION_EMOJIS = frozenset({"😂", "😁", "🤣", "👍", "👋", "😱", "😔", "😳", "😎", "🙄", "😒", "🤔", "😊", "🤗", "😴", "🤫", "😢", "😞", "🥳", "🎉"})


def enabled() -> bool:
    """运维可关掉本功能；不修改私有配置，也不放宽其他发送闸门。"""
    return os.environ.get("MAIBOT_UTYADUCK_STICKERS", "1").strip().lower() not in {"0", "false", "off", "no"}


class OfficialDuckStickers:
    """服务端目录、精确映射及原子冷却预占。"""

    def __init__(self) -> None:
        self._set_id: int | None = None
        self._set_access_hash: int | None = None
        self._documents: dict[int, Any] = {}
        self._emojis: dict[str, tuple[int, ...]] = {}
        self._lock = asyncio.Lock()
        self._last_sent: dict[str, float] = {}
        self._global_last: float | None = None
        self._pending = False

    def install(self, result: Any) -> None:
        """校验完整目录后原子替换；验证失败立即清空旧目录。"""
        from telethon.tl.types import Document, DocumentAttributeSticker, InputStickerSetID

        self._documents = {}
        self._emojis = {}
        meta = result.set
        if meta.short_name != PACK_SHORT_NAME or meta.id != PACK_SET_ID or not meta.access_hash:
            raise ValueError("官方贴纸套装身份不匹配")
        # Telegram 的 official=False 不等于盗版；用户已批准这个 canonical 套装。
        # 保留服务端元数据用于说明，不谎称 Telegram official 标志为 True。
        self.server_official = getattr(meta, "official", None)
        if getattr(meta, "masks", False) or getattr(meta, "emojis", False):
            raise ValueError("目标不是普通贴纸套装")
        if self._set_id is not None and (meta.id, meta.access_hash) != (self._set_id, self._set_access_hash):
            raise ValueError("贴纸套装身份发生变化，需人工复核")
        documents: dict[int, Any] = {}
        for document in result.documents:
            if not isinstance(document, Document) or not document.access_hash or not document.file_reference:
                continue
            attributes = [a for a in document.attributes if isinstance(a, DocumentAttributeSticker)]
            if len(attributes) != 1:
                continue
            source = attributes[0].stickerset
            if not isinstance(source, InputStickerSetID):
                continue
            if (source.id, source.access_hash) != (meta.id, meta.access_hash):
                continue
            documents[document.id] = document
        emojis: dict[str, tuple[int, ...]] = {}
        for pack in result.packs:
            if not isinstance(pack.emoticon, str) or not pack.emoticon:
                continue
            ids = tuple(sorted(set(i for i in pack.documents if i in documents)))
            if ids:
                emojis[pack.emoticon] = tuple(sorted(set(emojis.get(pack.emoticon, ()) + ids)))
        if not documents or not emojis:
            raise ValueError("官方贴纸目录没有可验证的 emoji 映射")
        self._set_id, self._set_access_hash = meta.id, meta.access_hash
        self._documents, self._emojis = documents, emojis

    async def refresh(self, client: Any) -> None:
        """发送前重取原生文件引用，不允许用过期缓存发送。"""
        from telethon.tl.functions.messages import GetStickerSetRequest
        from telethon.tl.types import InputStickerSetShortName

        async with self._lock:
            self._documents = {}
            self._emojis = {}
            result = await client(GetStickerSetRequest(
                stickerset=InputStickerSetShortName(PACK_SHORT_NAME), hash=0,
            ))
            self.install(result)

    def select(self, data: Any) -> tuple[str, Any] | None:
        """拒绝路径/URL/二进制及未知 ID；只收 emoji 或显式原生引用。"""
        if isinstance(data, str):
            emoji = data.strip()
            requested_id = None
        elif isinstance(data, dict) and set(data) <= {"pack", "emoji", "document_id"}:
            if data.get("pack") != PACK_SHORT_NAME or not isinstance(data.get("emoji"), str):
                return None
            emoji = data["emoji"].strip()
            requested_id = data.get("document_id")
            if requested_id is not None and (type(requested_id) is not int):
                return None
        else:
            return None
        ids = self._emojis.get(emoji, ())
        if not ids or (requested_id is not None and requested_id not in ids):
            return None
        if requested_id is None:
            if emoji not in REACTION_EMOJIS:
                return None
            # 多个文档同属一个标签时，优先选主 alt，避免泛化标签导致情绪错配。
            if len(ids) > 1:
                primary = [i for i in ids if any(
                    type(a).__name__ == "DocumentAttributeSticker" and a.alt == emoji
                    for a in self._documents[i].attributes
                )]
                if not primary:
                    return None
                # 同一 canonical alt 的多个动画不构成情绪歧义，固定排序选择。
                requested_id = primary[0]
        return emoji, self._documents[requested_id if requested_id is not None else ids[0]]

    def reserve(self, chat_id: str, *, now: float | None = None) -> bool:
        """全局单飞 + 保守冷却；成功后记账，失败仅撤销预占。"""
        now = time.monotonic() if now is None else now
        if self._pending:
            return False
        if not is_unlimited(chat_id) and (self._global_last is not None and now - self._global_last < 300):
            return False
        if not is_unlimited(chat_id) and chat_id in self._last_sent and now - self._last_sent[chat_id] < 900:
            return False
        self._pending = True
        return True

    def finish(self, chat_id: str, *, success: bool, now: float | None = None) -> None:
        if success:
            now = time.monotonic() if now is None else now
            self._global_last = now
            # 只保留仍有冷却意义的记录，避免长运行无限增长。
            self._last_sent = {key: stamp for key, stamp in self._last_sent.items() if now - stamp < 900}
            self._last_sent[chat_id] = now
        self._pending = False

    def planner_hint(self) -> str:
        """仅公布服务端实际可选 emoji；不虚构动作、情绪或图片含义。"""
        if not enabled() or not self._emojis:
            return ""
        emojis = " ".join(e for e in sorted(self._emojis) if self.select(e) is not None)
        return (
            "[Telegram 原生官方贴纸能力：仅 UtyaDuck。适合当前语境且只需简短情绪反应时，"
            "可以调用 official_duck_sticker(action=list) 查询，或 action=send 加一个下列精确 emoji；也可独立回复该 emoji。"
            "不要附加重复文字，不要把贴纸用于事实回答、技术说明或严肃求助。"
            "不要猜图片路径、文档 ID 或其他套装。无需反应时继续等待，不为使用贴纸而发言。"
            "冷却中不发送额外动作。可选 emoji：" + emojis + "]"
        )
