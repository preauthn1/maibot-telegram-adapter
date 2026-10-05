"""显式自账号观察的持久幂等历史写入，不调用消息接收或主动触发。"""
from datetime import datetime
from typing import Any, Dict

import asyncio
import json
import math

_LOCKS: Dict[str, asyncio.Lock] = {}


def persist_manual_message(message: Any) -> Any:
    """在现有消息库写锁内按流/平台/消息 ID upsert；编辑不得倒退。"""
    from sqlmodel import select

    from src.chat.message_receive.message import SessionMessage
    from src.common.database.database import get_db_session
    from src.common.database.database_model import Messages
    from src.common.utils.utils_message import _DB_WRITE_THREAD_LOCK

    with _DB_WRITE_THREAD_LOCK:
        with get_db_session() as db:
            from src.plugin_runtime.capabilities.telegram_event_journal import reconcile_message

            event = reconcile_message(db, message)
            if event and event["operation"] == "delete":
                return None
            rows = db.exec(select(Messages).where(
                Messages.platform == message.platform,
                Messages.session_id == message.session_id,
                Messages.message_id == message.message_id,
            )).all()
            if len(rows) > 1:
                raise ValueError("消息库存在重复 ID，需人工审查")
            fresh = message.to_db_instance()
            if rows:
                existing = rows[0]
                old_meta = json.loads(existing.additional_config or "{}")
                if old_meta.get("outgoing_provenance") != "manual_account":
                    raise ValueError("历史 ID 已由其他来源占有，拒绝覆盖")
                new_meta = message.message_info.additional_config
                if float(old_meta.get("telegram_edit_timestamp", 0)) >= float(new_meta["telegram_edit_timestamp"]):
                    return SessionMessage.from_db_instance(existing)
                fresh.id = existing.id
                # 原始发送时间不随编辑改变。
                fresh.timestamp = existing.timestamp
                for key in type(fresh).model_fields:
                    if key != "id":
                        setattr(existing, key, getattr(fresh, key))
                db.add(existing)
                result = SessionMessage.from_db_instance(existing)
            else:
                db.add(fresh)
                result = message
            # 显式提交先于内存发布；回调/RPC 丢失后重放不会增加第二行。
            db.commit()
            return result


async def append_manual_history(plugin_id: str, stream_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    from src.chat.heart_flow.heartflow_manager import heartflow_manager
    from src.chat.message_receive.chat_manager import chat_manager
    from src.chat.utils.utils import is_bot_self
    from src.plugin_runtime.host.message_utils import PluginMessageUtils

    if plugin_id != "preauthn1.telegram-user-adapter":
        raise ValueError("自账号历史仅允许 Telegram 账号适配器写入")
    if payload.get("platform") != "telegram" or payload.get("session_id") != stream_id:
        raise ValueError("历史平台或流归属不匹配")
    timestamp = float(payload["timestamp"])
    if not math.isfinite(timestamp) or timestamp <= 0:
        raise ValueError("无效原始时间戳")
    datetime.fromtimestamp(timestamp)
    message = PluginMessageUtils._build_session_message_from_dict(payload)
    meta = message.message_info.additional_config
    if (meta.get("outgoing_provenance") != "manual_account"
            or meta.get("human_authorship_verified") is not False
            or meta.get("owner_training_eligible") is not False
            or meta.get("maisaka_source_kind") != "guided_reply"):
        raise ValueError("历史来源声明无效")
    edited = float(meta["telegram_edit_timestamp"])
    if not math.isfinite(edited) or edited < 0:
        raise ValueError("无效编辑时间戳")
    if not is_bot_self(message.platform, message.message_info.user_info.user_id):
        raise ValueError("历史发送者并非当前账号")
    stream = chat_manager.get_existing_session_by_session_id(stream_id)
    if stream is None or stream.platform != message.platform:
        raise ValueError("目标聊天流未注册")
    group = message.message_info.group_info
    if group is not None:
        if stream.group_id != group.group_id:
            raise ValueError("群/话题归属不匹配")
    elif stream.group_id or stream.user_id != meta.get("platform_io_target_user_id"):
        raise ValueError("私聊对端归属不匹配")
    if any(segment.get("type") not in {"text", "reply"} for segment in payload["raw_message"]):
        raise ValueError("自账号历史仅支持文本、引用及文本媒体占位")
    # asyncio 锁跨 DB 与内存阶段，防止旧编辑在新编辑后发布。
    from src.plugin_runtime.capabilities.telegram_events import _LOCK

    async with _LOCK:
        runtime = await heartflow_manager.get_or_create_heartflow_chat(stream_id)
        stored = persist_manual_message(message)
        if stored is None:
            return {"success": True, "history_only": True, "changed": 0}
        history = await runtime._reasoning_engine._build_history_message(stored, source_kind="guided_reply")
        from src.plugin_runtime.capabilities.telegram_event_journal import suppress_live_message

        suppress_live_message(stored)
        if stored.message_info.additional_config.get("telegram_deleted"):
            return {"success": True, "history_only": True, "changed": 0}
        if history is None:
            raise ValueError("历史消息构造失败")
        for index, item in enumerate(runtime._chat_history):
            if getattr(item, "message_id", None) == stored.message_id:
                original = getattr(item, "original_message", None)
                if original is not None and original.platform == stored.platform:
                    runtime._chat_history[index] = history
                    break
        else:
            # 重放/编辑按原始发生时间插入，不能伪装成刚刚说的新话。
            index = next((i for i, item in enumerate(runtime._chat_history)
                          if item.timestamp > stored.timestamp), len(runtime._chat_history))
            runtime._chat_history.insert(index, history)
        return {"success": True, "stream_id": stream_id, "source_kind": "guided_reply",
                "provenance": "manual_account", "message_id": stored.message_id, "history_only": True}
