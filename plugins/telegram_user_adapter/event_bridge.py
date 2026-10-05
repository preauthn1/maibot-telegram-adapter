"""事件适配层。GPL-3.0；2026-10-06 修改；见 EVENTS_PORT_NOTICE.md。"""
from typing import Any
import asyncio
import functools
import time

from .event_dispatch import EventDispatch
from .utils import build_topic_group_id


def p_self_id(plugin):
    return str(plugin._self_account_id)


def tracked(method):
    @functools.wraps(method)
    async def wrapped(self, *args):
        if self.closed:
            return
        task = asyncio.current_task()
        self.active.add(task)
        try:
            return await method(self, *args)
        finally:
            self.active.discard(task)
    return wrapped


class EventBridge:
    def __init__(self, plugin: Any):
        self.plugin = plugin
        self.started = time.time()
        self.dispatch = EventDispatch(plugin._on_new_message)
        self.closed = False
        self.active = set()
        from .catchup import DurableCatchup
        self.catchup = DurableCatchup(self)

    async def connected(self):
        await self.catchup.connected()

    def key(self, event):
        codec = self.plugin._inbound_codec
        topic = codec._resolve_topic_thread_id(event.message)
        return (str(event.chat_id), None if event.is_private else topic)

    def allowed(self, event):
        p = self.plugin
        if self.closed or p._chat_filter is None or p._inbound_codec is None:
            return False
        if event.chat_id is None or event.sender_id is None:
            return False
        s = p._load_settings().chat
        chat = str(event.chat_id)
        if not event.is_private:
            if not s.enable_group_chat:
                return False
            if s.group_list_type == "whitelist" and not p._chat_filter._id_matches(chat, list(s.group_list)):
                return False
        # 不补取 sender；无缓存 sender 时不能断言非 bot，保守跳过补历史。
        return p._chat_filter.check_allow(s, user_id=chat if event.is_private else str(event.sender_id),
            chat_id=chat, is_private=bool(event.is_private),
            is_channel=bool(event.is_channel) and not bool(event.is_group),
            sender_is_bot=bool(getattr(getattr(event, "sender", None), "bot", False)))

    @tracked
    async def new(self, event):
        if self.closed:
            return
        # 手动 outgoing 路径与回执策略保持原样，不经过入站 catch-up。
        if event.message.out:
            await self.plugin._on_new_message(event)
            return
        if not self.allowed(event):
            # 普通实时消息仍由现有策略处理（含陌生私聊策略）。
            if event.message.date.timestamp() >= max(self.started, time.time() - 60):
                await self.plugin._on_new_message(event)
            return
        if event.message.date.timestamp() < max(self.started, time.time() - 60):
            await self.history(event, "catchup")
            return
        self.dispatch.submit(self.key(event), int(event.message.id), event)

    @tracked
    async def edited(self, event):
        if self.closed:
            return
        if event.message.out:
            await self.plugin._on_message_edited(event)
            return
        if not self.allowed(event):
            return
        key, mid = self.key(event), int(event.message.id)
        # 先持久化编辑，RPC 被取消/原文已在 host 队列中也不能丢失。
        await self.history(event, "edit")
        if self.dispatch.replace(key, mid, event):
            return
        # 取消已出队但仍处于阅读/路由 await 的旧版本，再只改历史。
        await self.dispatch.cancel(key, mid)
        await self.plugin._on_message_edited(event)

    async def history(self, event, operation):
        if not self.allowed(event):
            return
        if operation == "catchup":
            # 自己不能被补历史路径误标为外部用户；沿用所有权账本。
            if event.message.out or str(event.sender_id) == p_self_id(self.plugin):
                if not event.message.out:
                    return False
                from .manual_history import ingest_manual_outgoing
                return await ingest_manual_outgoing(self.plugin, event)
            if getattr(event, "sender", None) is None:
                return False
        p = self.plugin
        chat, topic = self.key(event)
        target = chat if event.is_private else build_topic_group_id(event.chat_id, topic)
        sid = await p._resolve_host_stream_id(target)
        if self.closed or (not sid and operation == "catchup"):
            return
        sid = sid or "telegram-pending-event"
        text = event.message.message or ""
        if event.message.media is not None:
            text += "\n[附件未解析]"
        from .spam_filter import detect_spam
        from .content_safety import detect_nsfw
        if operation == "catchup" and (detect_spam(text)[0] or detect_nsfw(text)[0]):
            return
        result = await p.ctx.maisaka.context.append(stream_id=sid, telegram_event={
            "operation": operation, "chat_id": chat, "target": target,
            "private": bool(event.is_private), "topic": topic,
            "message_id": str(event.message.id), "sender_id": str(event.sender_id),
            "text": text, "timestamp": event.message.date.timestamp(),
            "edit_timestamp": event.message.edit_date.timestamp() if event.message.edit_date else 0,
        })
        if not isinstance(result, dict) or result.get("success") is not True:
            raise RuntimeError("Telegram 历史变更未确认")
        return True

    @tracked
    async def deleted(self, event):
        if self.closed:
            return
        # 无 peer 的 UpdateDeleteMessages 只可查询非 channel 的已存精确消息；
        # host 拒绝歧义，绝不根据 ID 猜作者或把 channel ID 跨群匹配。
        chat = str(event.chat_id) if event.chat_id is not None else None
        ids = [str(mid) for mid in event.deleted_ids]
        result = await self.plugin.ctx.maisaka.context.append(stream_id="telegram-event-delete",
            telegram_event={"operation": "delete", "chat_id": chat, "message_ids": ids})
        if not isinstance(result, dict) or result.get("success") is not True:
            raise RuntimeError("Telegram 删除未确认")
        for key, mid in list(self.dispatch.tasks):
            channel = int(key[0]) <= -1000000000000
            if str(mid) in ids and ((chat is not None and key[0] == chat) or (chat is None and not channel)):
                await self.dispatch.cancel(key, mid)
        if self.closed:
            return

    @tracked
    async def typing(self, update):
        if self.closed:
            return
        from telethon.tl import types
        if isinstance(update, types.UpdateUserTyping):
            key = (str(update.user_id), None)
        elif isinstance(update, types.UpdateChatUserTyping):
            key = (str(-update.chat_id), None)
        elif isinstance(update, types.UpdateChannelUserTyping):
            key = (str(-1000000000000 - update.channel_id), getattr(update, "top_msg_id", None))
        else:
            return
        self.dispatch.typing(key, not isinstance(update.action, types.SendMessageCancelAction))

    async def close(self):
        self.closed = True
        await self.catchup.close()
        active = [task for task in self.active if task is not asyncio.current_task()]
        for task in active:
            task.cancel()
        try:
            if active:
                await asyncio.gather(*active, return_exceptions=True)
        finally:
            await self.dispatch.close()
