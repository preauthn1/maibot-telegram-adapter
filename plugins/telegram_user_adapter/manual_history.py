"""Telegram 自账号观察仅写历史，不进入入站路由或主人训练语料。"""
from typing import Any

from .constants import PLATFORM_NAME
from .utils import build_topic_group_id


async def ingest_manual_outgoing(plugin: Any, event: Any) -> bool | None:
    settings = plugin._load_settings()
    if settings.behavior.ignore_outgoing_from_other_devices:
        return
    client = plugin._tg_client
    if client is None or plugin._inbound_codec is None or plugin._chat_filter is None:
        return
    message = event.message
    chat = str(event.chat_id)
    if str(event.sender_id) != plugin._self_account_id or not message.out:
        return
    # Match ordinary ingress's group precheck: an empty whitelist denies all.
    # check_allow alone treats an empty group whitelist as unrestricted.
    if chat.startswith("-"):
        chat_settings = settings.chat
        if not chat_settings.enable_group_chat:
            return
        if (chat_settings.group_list_type == "whitelist"
                and not plugin._chat_filter._id_matches(chat, list(chat_settings.group_list))):
            return
    # 私聊过滤对象是对端，不是自己的 sender_id。
    if not plugin._chat_filter.check_allow(
        settings.chat, user_id=chat if event.is_private else str(event.sender_id),
        chat_id=chat, is_private=bool(event.is_private),
        is_channel=bool(event.is_channel) and not bool(event.is_group), sender_is_bot=False,
    ):
        return
    ownership = client.client.outgoing_ownership
    classification = await ownership.classify(chat, int(message.id), message.date.timestamp())
    if classification != "manual_account":
        if classification == "unknown":
            plugin.ctx.logger.warning("自账号消息所有权不确定，未写历史: chat=%s mid=%s", chat, message.id)
        return
    codec = plugin._inbound_codec
    thread = codec._resolve_topic_thread_id(message)
    target = chat if event.is_private else build_topic_group_id(event.chat_id, thread)
    stream_id = await plugin._resolve_host_stream_id(target)
    if not stream_id:
        plugin.ctx.logger.warning("自账号历史未写入：聊天流尚未注册 chat=%s", target)
        return
    # 无网络/识图/已读/反应；媒体只保留真实文字说明和显式占位。
    text = message.message or ""
    if message.media is not None:
        text += "\n[附件未解析]"
    if not text:
        return
    reply_id = codec._resolve_real_reply_id(message)
    segments = []
    if reply_id is not None:
        quote = getattr(message.reply_to, "quote_text", None)
        segments.append({"type": "reply", "data": {
            "target_message_id": str(reply_id), "target_message_content": quote,
        }})
        # guided_reply 的 legacy replyer 展示通常省略 ReplyComponent；显式保留引用关系。
        text = f"[回复消息 {reply_id}]" + (f" 引用：{quote}\n" if quote else "\n") + text
    segments.append({"type": "text", "data": text})
    additional = {
        "maisaka_source_kind": "guided_reply", "outgoing_provenance": "manual_account",
        "human_authorship_verified": False, "owner_training_eligible": False,
        "telegram_chat_id": chat, "message_thread_id": thread,
        "telegram_edit_timestamp": message.edit_date.timestamp() if message.edit_date else 0,
        "platform_io_target_user_id" if event.is_private else "platform_io_target_group_id": target,
    }
    # Pure presentation metadata only; never call the inbound download path.
    from dataclasses import asdict
    from .fidelity.formatting import inbound_entities, inbound_markdown
    from .fidelity.provenance import provenance
    from .fidelity.preview import existing_preview

    additional["telegram_provenance"] = provenance(message)
    original_text = message.message or ""
    if original_text:
        entities = getattr(message, "entities", None)
        additional["telegram_markdown"] = inbound_markdown(original_text, entities)
        additional["telegram_entities"] = [asdict(e) for e in inbound_entities(original_text, entities)]
    preview = existing_preview(message)
    if preview:
        additional["telegram_preview"] = preview
    info = {"user_info": {"user_id": plugin._self_account_id, "user_nickname": plugin._self_account_id},
            "additional_config": additional}
    if not event.is_private:
        info["group_info"] = {"group_id": target, "group_name": target}
    payload = {
        "message_id": str(message.id), "timestamp": str(message.date.timestamp()),
        "platform": PLATFORM_NAME, "session_id": stream_id, "message_info": info,
        "raw_message": segments, "processed_plain_text": text,
        "reply_to": str(reply_id) if reply_id is not None else None,
    }
    result = await plugin.ctx.maisaka.context.append(
        stream_id=stream_id, segments=segments, source_kind="guided_reply",
        message_id=str(message.id), history_only_message=payload,
    )
    if not isinstance(result, dict) or result.get("success") is not True:
        raise RuntimeError("自账号历史提交未确认")
    return True
