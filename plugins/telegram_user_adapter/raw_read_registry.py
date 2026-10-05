# SPDX-License-Identifier: GPL-3.0-or-later
# Modified 2026-10-06; see STICKER_RAW_NOTICES.md.
"""经过代码审查的只读适配器注册表，不是任意 MTProto 执行器。"""
from types import MappingProxyType
from typing import Any

import asyncio
import json


async def message_ids(client: Any, chat: int, topic: int | None, params: dict) -> dict:
    from .native_tools import old_messages
    if set(params) != {"ids"}:
        raise ValueError("仅接受 ids；peer 由当前会话决定")
    return await old_messages(client, chat, topic, params["ids"])


async def history(client: Any, chat: int, topic: int | None, params: dict) -> dict:
    from .native_tools import in_scope, positive_id, project_message
    if set(params) - {"limit", "before_id"}:
        raise ValueError("不允许指定其他 peer / filter / TL 类型")
    limit, before = params.get("limit", 5), params.get("before_id", 0)
    if type(limit) is not int or not 1 <= limit <= 10 or type(before) is not int:
        raise ValueError("limit 必须为 1–10；before_id 必须为整数")
    if before != 0:
        before = positive_id(before)
    kwargs = {"limit": limit, "offset_id": before}
    if topic is not None:
        kwargs["reply_to"] = topic
    messages = await asyncio.wait_for(client.get_messages(chat, **kwargs), 15)
    safe = [project_message(m) for m in messages[:limit] if in_scope(m, chat, topic)]
    return {"success": True, "messages": safe, "content": json.dumps(safe, ensure_ascii=False), "scope_filtered": True}


async def info(client: Any, chat: int, topic: int | None, params: dict) -> dict:
    from .native_tools import chat_info
    if params:
        raise ValueError("scoped.chatInfo 不接受参数")
    return await chat_info(client, chat, topic)


# 扩展必须增加一个有界实现并在此静态注册；模型不能注册 callable/TL 类型。
READ_REGISTRY = MappingProxyType({
    "messages.getMessages": (message_ids, "当前话题最多十个消息 ID；非原始 TL 响应"),
    "messages.getHistory": (history, "当前话题最多十条；SDK get_messages 有界投影"),
    "scoped.chatInfo": (info, "当前会话公开概要；按实体类型读取，非任意 GetFull 请求"),
})
UNAVAILABLE = ("arbitrary MTProto", "dynamic TL constructors", "InvokeWith wrappers",
               "cross-chat reads", "member enumeration", "global search", "sticker-set installation",
               "auth/account/contacts/payments", "upload/download", "send/edit/delete/join/leave")
