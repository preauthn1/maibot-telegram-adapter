# SPDX-License-Identifier: GPL-3.0-or-later
# Modified 2026-10-06: scoped port from KumaTea/MaiBot-Telegram-Full
# 58799cd356ad69f2b3b3cfb2e04c0ea5c59489fb. See PORT-NOTICES.md.
"""只复用已登录客户端；拒绝任意 peer、话题越界和动态 TL 构造。"""
from __future__ import annotations

from typing import Any

import asyncio
import json
import re


def positive_id(value: Any) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[1-9][0-9]{0,9}", str(value)):
        raise ValueError("消息 ID 必须为正整数")
    result = int(value)
    if result > 2147483647:
        raise ValueError("消息 ID 超出范围")
    return result


def in_scope(message: Any, chat: int, topic: int | None) -> bool:
    # 私聊 / 普通群的 getMessages 可能返回其他对话的全局 ID；逐条复核。
    if message is None or getattr(message, "chat_id", None) != chat:
        return False
    header = getattr(message, "reply_to", None)
    forum = bool(getattr(header, "forum_topic", False))
    top = getattr(header, "reply_to_top_id", None)
    if forum and top is None:
        top = getattr(header, "reply_to_msg_id", None)
    if topic is not None:
        return message.id == topic or (forum and top == topic)
    # 未分话题的流不得窥读任何论坛话题（含 General）；宁可少返回。
    return not forum


def project_message(message: Any) -> dict[str, Any]:
    return {"message_id": str(message.id), "sender_id": str(message.sender_id or ""),
            "text": str(message.message or "")[:2000], "has_media": message.media is not None}


async def old_messages(client: Any, chat: int, topic: int | None, ids: list[Any]) -> dict[str, Any]:
    if not isinstance(ids, list) or not 1 <= len(ids) <= 10:
        raise ValueError("每次只能查询 1–10 条当前聊天消息")
    ids = list(dict.fromkeys(positive_id(x) for x in ids))
    messages = await asyncio.wait_for(client.get_messages(chat, ids=ids), timeout=15)
    safe = [project_message(m) for m in messages[:len(ids)] if in_scope(m, chat, topic) and m.id in ids]
    # 不区分不存在与越权，避免枚举侧信道。
    return {"success": True, "messages": safe, "content": json.dumps(safe, ensure_ascii=False),
            "unavailable_count": len(ids) - len(safe)}


async def chat_info(client: Any, chat: int, topic: int | None) -> dict[str, Any]:
    """只读取当前群公开概要，不枚举成员或返回访问凭据。"""
    from telethon import functions, types, utils

    async def fetch() -> dict[str, Any]:
        entity = await client.get_entity(chat)
        if utils.get_peer_id(entity) != chat:
            raise ValueError("聊天实体与目标不一致")
        info = {"chat_id": str(chat), "topic_id": topic,
                "title": str(getattr(entity, "title", None) or getattr(entity, "first_name", ""))[:200],
                "username": str(getattr(entity, "username", "") or "")[:64],
                "forum": bool(getattr(entity, "forum", False))}
        full = None
        if isinstance(entity, types.Channel):
            full = (await client(functions.channels.GetFullChannelRequest(entity))).full_chat
        elif isinstance(entity, types.Chat):
            full = (await client(functions.messages.GetFullChatRequest(entity.id))).full_chat
        if full is not None:
            if full.id != entity.id:
                raise ValueError("群概要与目标不一致")
            info["about"] = str(getattr(full, "about", "") or "")[:2000]
            count = getattr(full, "participants_count", None)
            if count is None:
                count = getattr(entity, "participants_count", None)
            if type(count) is int and count >= 0:
                info["members_count"] = count
        return {"success": True, "chat": info, "content": json.dumps(info, ensure_ascii=False)}

    return await asyncio.wait_for(fetch(), timeout=15)


from .raw_read_registry import READ_REGISTRY, UNAVAILABLE

RAW_ALLOW = frozenset(READ_REGISTRY)
# 即使将来扩大 allow，也必须先经过禁止项；不接受 InvokeWith* 包装器 / auth / contacts。
RAW_DENY = re.compile(r"(?i)(auth|account|contacts|payments|upload|download|send|delete|edit|join|invite|leave|update|import|export|invoke|forward|report|block|readHistory)")


async def raw_read(client: Any, chat: int, topic: int | None, method: str,
                   params: dict[str, Any], enabled: bool = False) -> dict[str, Any]:
    if not enabled:
        raise ValueError("只读适配器默认关闭；不支持任意 MTProto")
    if not isinstance(method, str) or RAW_DENY.search(method) or method not in READ_REGISTRY:
        return {"success": False, "error": "方法不可用；仅支持注册的有界只读适配器",
                "available_methods": list(READ_REGISTRY), "unavailable": list(UNAVAILABLE)}
    if not isinstance(params, dict) or len(json.dumps(params)) > 2048:
        raise ValueError("参数无效或过大")
    handler, semantics = READ_REGISTRY[method]
    result = await handler(client, chat, topic, params)
    return {**result, "adapter_method": method, "semantics": semantics, "raw_mtproto": False}


from .observed_stickers import ObservedStickers  # 保留已有导入路径
