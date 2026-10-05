"""Telegram 历史事件；不进入 route_message/Planner。GPL-3.0，修改于 2026-10-06。
来源说明见 EVENTS_PORT_NOTICE.md。删除保留墓碑，防止旧重放复活。
"""
from datetime import datetime
from typing import Any, Dict
import asyncio
import json
import math

_LOCK = asyncio.Lock()


def matches_stream(stream, event):
    """仅接受 host 已注册流；private 的对象是对端而非作者。"""
    if stream is None or stream.platform != "telegram":
        return False
    if event["private"]:
        return not stream.group_id and str(stream.user_id) == event["target"] == event["chat_id"]
    target = event["chat_id"]
    if event.get("topic"):
        target += "::tg-topic::mt=" + str(event["topic"])
    return str(stream.group_id) == event["target"] == target


def deletion_matches(stream, chat):
    if stream is None or stream.platform != "telegram":
        return False
    # group_id 的编码由 adapter utils 构造；private 不用 sender 推断。
    base = str(stream.group_id).split("::tg-topic::", 1)[0] if stream.group_id else str(stream.user_id)
    if chat is None:
        return int(base) > -1000000000000
    return base == chat


def validate_event(event):
    if event.get("operation") not in {"edit", "delete", "catchup"}:
        raise ValueError("未知事件")
    if event["operation"] == "delete":
        ids = event.get("message_ids", [])
        if not ids or len(ids) > 1000 or any(not str(mid).isdigit() for mid in ids):
            raise ValueError("无效删除 ID")
        chat = event.get("chat_id")
        if chat is not None and (not isinstance(chat, str) or not chat.lstrip("-").isdigit()):
            raise ValueError("无效删除聊天 ID")
        return
    if not str(event.get("message_id", "")).isdigit() or not str(event.get("sender_id", "")).lstrip("-").isdigit():
        raise ValueError("缺少真实消息/作者 ID")
    for name in ("timestamp", "edit_timestamp"):
        n = float(event[name])
        if not math.isfinite(n) or n < 0 or (name == "timestamp" and n == 0):
            raise ValueError("无效时间")
    chat = event["chat_id"]
    if not isinstance(chat, str) or not chat.lstrip("-").isdigit():
        raise ValueError("无效聊天 ID")
    target = chat
    if not event["private"] and event.get("topic"):
        if not str(event["topic"]).isdigit():
            raise ValueError("无效话题 ID")
        target += "::tg-topic::mt=" + str(event["topic"])
    if event["target"] != target:
        raise ValueError("事件目标归属不匹配")
    if len(event["text"]) > 65536:
        raise ValueError("历史文本过长")


def persist_event(stream_id, event):
    from sqlmodel import select
    from src.chat.message_receive.chat_manager import chat_manager
    from src.chat.message_receive.message import SessionMessage
    from src.common.database.database import get_db_session
    from src.common.database.database_model import Messages
    from src.common.utils.utils_message import _DB_WRITE_THREAD_LOCK
    from src.plugin_runtime.host.message_utils import PluginMessageUtils

    from src.plugin_runtime.capabilities.telegram_event_journal import write_event, reconcile_message

    operation = event["operation"]
    changed = []
    with _DB_WRITE_THREAD_LOCK:
        with get_db_session() as db:
            write_event(db, event)
            if operation == "delete":
                rows = db.exec(select(Messages).where(Messages.platform == "telegram",
                    Messages.message_id.in_(event["message_ids"]))).all()
                rows = [row for row in rows if deletion_matches(
                    chat_manager.get_existing_session_by_session_id(row.session_id), event["chat_id"])]
                # peer-less updates have account-global non-channel IDs. Any ambiguity fails closed.
                for mid in event["message_ids"]:
                    if event["chat_id"] is None and len({row.session_id for row in rows if row.message_id == mid}) > 1:
                        raise ValueError("无 peer 删除存在歧义")
            else:
                stream = chat_manager.get_existing_session_by_session_id(stream_id)
                if stream is None and operation == "edit":
                    db.commit()  # 尚未注册的真实 chat/target 编辑持久等待原消息。
                    return []
                if not matches_stream(stream, event):
                    raise ValueError("流归属不匹配")
                rows = db.exec(select(Messages).where(Messages.platform == "telegram",
                    Messages.session_id == stream_id, Messages.message_id == event["message_id"])).all()
                if len(rows) > 1:
                    raise ValueError("历史 ID 重复")
                if not rows and operation == "edit":
                    db.commit()  # 编辑等待真实原文，不创建假作者/假消息。
                    return []
                if not rows:
                    info = {"user_info": {"user_id": event["sender_id"], "user_nickname": event["sender_id"]},
                            "additional_config": {"telegram_chat_id": event["chat_id"],
                            "platform_io_target_user_id": event["target"],
                            "telegram_edit_timestamp": event["edit_timestamp"],
                            "owner_training_eligible": False, "telegram_history_only": True}}
                    if not event["private"]:
                        info["group_info"] = {"group_id": event["target"], "group_name": event["target"]}
                    payload = {"platform": "telegram", "session_id": stream_id,
                        "message_id": event["message_id"], "timestamp": str(event["timestamp"]),
                        "message_info": info, "raw_message": [{"type": "text", "data": event["text"]}],
                        "processed_plain_text": event["text"]}
                    message = PluginMessageUtils._build_session_message_from_dict(payload)
                    pending = reconcile_message(db, message)
                    if pending and pending["operation"] == "delete":
                        db.commit()
                        return []
                    fresh = message.to_db_instance()
                    db.add(fresh)
                    rows = [fresh]
            for row in rows:
                meta = json.loads(row.additional_config or "{}")
                if operation != "delete":
                    if meta.get("telegram_deleted"):
                        continue
                    if str(row.user_id) != event["sender_id"]:
                        raise ValueError("原作者不匹配")
                    if operation == "catchup" and row.id is not None:
                        changed.append(SessionMessage.from_db_instance(row))
                        continue
                    if operation == "edit" and float(meta.get("telegram_edit_timestamp", 0)) >= event["edit_timestamp"]:
                        changed.append(SessionMessage.from_db_instance(row))
                        continue
                    text = row.processed_plain_text if operation == "catchup" else event["text"]
                    if operation == "edit":
                        meta["telegram_edit_timestamp"] = event["edit_timestamp"]
                else:
                    text = "[消息已删除]"
                    meta["telegram_deleted"] = True
                # 使用现有 SessionMessage 序列化契约，不猜 msgpack 格式。
                message = SessionMessage.from_db_instance(row)
                message.raw_message = PluginMessageUtils._message_sequence_from_dict([{"type": "text", "data": text}])
                message.processed_plain_text = text
                message.message_info.additional_config = meta
                fresh = message.to_db_instance()
                row.raw_content = fresh.raw_content
                row.processed_plain_text = text
                row.additional_config = json.dumps(meta, ensure_ascii=False)
                db.add(row)
                changed.append(SessionMessage.from_db_instance(row))
            db.commit()
    return changed


async def apply_telegram_event(plugin_id: str, stream_id: str, event: Dict[str, Any]):
    if plugin_id != "preauthn1.telegram-user-adapter":
        raise ValueError("事件写入仅允许 Telegram 适配器")
    validate_event(event)
    from src.chat.heart_flow.heartflow_manager import heartflow_manager
    async with _LOCK:
        messages = persist_event(stream_id, event)
        for message in messages:
            # 不创建 runtime，不触发回复，不发 receipt；离线流下次从 DB 恢复。
            runtime = heartflow_manager.heartflow_chat_list.get(message.session_id)
            if runtime is None:
                continue
            runtime.message_cache[:] = [item for item in runtime.message_cache
                if not (item.message_id == message.message_id and item.platform == "telegram")]
            if event["operation"] == "delete":
                runtime._chat_history[:] = [item for item in runtime._chat_history
                    if not (getattr(item, "message_id", None) == message.message_id
                    and getattr(getattr(item, "original_message", None), "platform", None) == "telegram")]
                continue
            history = await runtime._reasoning_engine._build_history_message(message, source_kind="telegram_history")
            from src.plugin_runtime.capabilities.telegram_event_journal import suppress_live_message
            suppress_live_message(message)
            if message.message_info.additional_config.get("telegram_deleted"):
                continue
            if history is None:
                raise ValueError("历史消息构造失败")
            for i, item in enumerate(runtime._chat_history):
                if (getattr(item, "message_id", None) == message.message_id
                        and getattr(getattr(item, "original_message", None), "platform", None) == "telegram"):
                    runtime._chat_history[i] = history
                    break
            else:
                i = next((i for i, item in enumerate(runtime._chat_history)
                          if item.timestamp > message.timestamp), len(runtime._chat_history))
                runtime._chat_history.insert(i, history)
        return {"success": True, "history_only": True, "changed": len(messages)}
