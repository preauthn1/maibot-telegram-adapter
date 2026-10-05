"""持久事件屏障：与普通消息写入共享事务及线程锁，不推断作者/会话 ID。"""
import json
from sqlalchemy import text


def ensure_journal(db):
    # 同一 SQLite 数据库；事务回滚同时回滚消息和事件。无过期淘汰，防止旧队列复活。
    db.execute(text("CREATE TABLE IF NOT EXISTS telegram_event_journal ("
        "kind TEXT NOT NULL, scope TEXT NOT NULL, message_id TEXT NOT NULL, "
        "payload TEXT NOT NULL, PRIMARY KEY(kind, scope, message_id))"))


def write_event(db, event):
    ensure_journal(db)
    if event["operation"] == "delete":
        scope = "peerless" if event["chat_id"] is None else "chat:" + event["chat_id"]
        for mid in event["message_ids"]:
            db.execute(text("INSERT INTO telegram_event_journal VALUES ('delete', :scope, :mid, '{}') "
                "ON CONFLICT(kind, scope, message_id) DO NOTHING"), {"scope": scope, "mid": str(mid)})
    elif event["operation"] == "edit":
        scope = ("private:" if event["private"] else "group:") + event["target"]
        args = {"scope": scope, "mid": event["message_id"]}
        previous = db.execute(text("SELECT payload FROM telegram_event_journal "
            "WHERE kind='edit' AND scope=:scope AND message_id=:mid"), args).scalar()
        if previous:
            previous = json.loads(previous)
            if previous["sender_id"] != event["sender_id"]:
                raise ValueError("待处理编辑作者不匹配")
            if previous["edit_timestamp"] >= event["edit_timestamp"]:
                return
        args["payload"] = json.dumps(event, ensure_ascii=False)
        db.execute(text("INSERT INTO telegram_event_journal VALUES ('edit', :scope, :mid, :payload) "
            "ON CONFLICT(kind, scope, message_id) DO UPDATE SET payload=excluded.payload"), args)


def pending_event(db, message):
    if message.platform != "telegram" or not str(message.message_id).isdigit():
        return None
    from src.chat.message_receive.chat_manager import chat_manager
    stream = chat_manager.get_existing_session_by_session_id(message.session_id)
    if stream is None or stream.platform != "telegram":
        # 不用作者 ID 推断私聊对象，也不自行计算 session_id。
        raise ValueError("Telegram 消息缺少已注册聊天流")
    group = str(stream.group_id) if stream.group_id else None
    target = group or str(stream.user_id)
    chat = target.split("::tg-topic::", 1)[0]
    ensure_journal(db)
    scopes = ["chat:" + chat]
    if int(chat) > -1000000000000:
        scopes.append("peerless")
    for scope in scopes:
        if db.execute(text("SELECT 1 FROM telegram_event_journal WHERE kind='delete' "
                "AND scope=:scope AND message_id=:mid"), {"scope": scope, "mid": message.message_id}).first():
            return {"operation": "delete"}
    payload = db.execute(text("SELECT payload FROM telegram_event_journal WHERE kind='edit' "
        "AND scope=:scope AND message_id=:mid"), {"scope": ("group:" if group else "private:") + target,
        "mid": message.message_id}).scalar()
    event = json.loads(payload) if payload else None
    if event and event["sender_id"] != str(message.message_info.user_info.user_id):
        raise ValueError("待处理编辑作者不匹配")
    return event


def reconcile_message(db, message):
    """调用方持有写锁；编辑只在真实原消息出现后物化，删除不创建假消息。"""
    event = pending_event(db, message)
    if event is None:
        return None
    meta = message.message_info.additional_config
    meta["telegram_history_only"] = True
    if event["operation"] == "delete":
        meta["telegram_deleted"] = True
        return event
    if float(meta.get("telegram_edit_timestamp", 0)) <= event["edit_timestamp"]:
        from src.plugin_runtime.host.message_utils import PluginMessageUtils
        message.raw_message = PluginMessageUtils._message_sequence_from_dict(
            [{"type": "text", "data": event["text"]}])
        message.processed_plain_text = event["text"]
        meta["telegram_edit_timestamp"] = event["edit_timestamp"]
    return event


def store_telegram_message(db, message):
    """普通写入入口在同一锁/事务内执行；返回 True 表示已处理。"""
    if message.platform != "telegram" or not str(message.message_id).isdigit():
        return False
    from sqlmodel import select
    from src.common.database.database_model import Messages
    event = reconcile_message(db, message)
    if event and event["operation"] == "delete":
        return True
    rows = db.exec(select(Messages).where(Messages.platform == "telegram",
        Messages.session_id == message.session_id, Messages.message_id == message.message_id)).all()
    if len(rows) > 1:
        raise ValueError("Telegram 历史 ID 重复")
    if rows:
        # 重放原文不得覆盖已提交的编辑、墓碑或手动自发历史。
        return True
    from src.common.utils.utils_message import MessageUtils
    MessageUtils._persist_image_components(message.raw_message.components, db)
    db.add(message.to_db_instance())
    return True


def suppress_live_message(message):
    """入队前同步检查：没有 await 间隙；旧 edit/delete 只能留历史。"""
    if message.platform != "telegram" or not str(message.message_id).isdigit():
        return False
    from src.common.database.database import get_db_session
    from src.common.utils.utils_message import _DB_WRITE_THREAD_LOCK
    with _DB_WRITE_THREAD_LOCK:
        with get_db_session() as db:
            event = reconcile_message(db, message)
    return bool(event or message.message_info.additional_config.get("telegram_history_only")
                or message.message_info.additional_config.get("telegram_deleted"))


async def publish_pending_history(message):
    """晚提交的原文已有真实作者：仅补当前运行时历史，不再次路由。"""
    from src.common.database.database import get_db_session
    from src.common.utils.utils_message import _DB_WRITE_THREAD_LOCK
    from src.plugin_runtime.capabilities.telegram_events import apply_telegram_event
    with _DB_WRITE_THREAD_LOCK:
        with get_db_session() as db:
            event = pending_event(db, message)
    if event and event["operation"] == "edit":
        await apply_telegram_event("preauthn1.telegram-user-adapter", message.session_id, event)
