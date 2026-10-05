"""有界持久补历史。GPL-3.0；2026-10-06；保留 EVENTS_PORT_NOTICE.md。
只复用已有用户连接；Bot 历史不支持。水位是已确认最近窗口，不代表完整归档。
"""
from contextlib import closing
from types import SimpleNamespace
import asyncio
import re
import sqlite3


class Watermarks:
    """账号/真实目标隔离；ACK 后单调提交，崩溃重放由 Host journal 去重。"""
    def __init__(self, path, account):
        self.path, self.account = path, str(account)
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS catchup_watermark ("
                       "account TEXT NOT NULL, target TEXT NOT NULL, mid INTEGER NOT NULL, "
                       "PRIMARY KEY(account,target))")
        path.chmod(0o600)

    def connect(self):
        return sqlite3.connect(self.path, timeout=0.1)

    def read(self, target):
        with closing(self.connect()) as db:
            row = db.execute("SELECT mid FROM catchup_watermark WHERE account=? AND target=?",
                             (self.account, target)).fetchone()
        return row[0] if row else 0

    def advance(self, target, mid):
        with closing(self.connect()) as db, db:
            db.execute("INSERT INTO catchup_watermark VALUES (?,?,?) "
                       "ON CONFLICT(account,target) DO UPDATE SET mid=MAX(mid,excluded.mid)",
                       (self.account, target, int(mid)))


def parse_target(target):
    """拒绝别名/用户名/自动修复，避免把私聊误当频道或跨话题。"""
    match = re.fullmatch(r"(-?[1-9][0-9]*)(?:::tg-topic::mt=([1-9][0-9]*))?", target)
    if not match:
        raise ValueError("补历史目标必须为规范 chat_id/话题键")
    chat, topic = match.groups()
    if topic and int(chat) > -1000000000000:
        raise ValueError("话题补历史仅支持 channel/supergroup")
    return int(chat), int(topic) if topic else None


class DurableCatchup:
    def __init__(self, bridge):
        self.bridge = bridge
        self.task = None
        self.lock = asyncio.Lock()
        self.watermarks = None

    async def connected(self):
        async with self.lock:
            await self.cancel()
            if self.bridge.closed:
                return
            p = self.bridge.plugin
            settings = p._load_settings()
            if not settings.catchup.targets:
                return
            if settings.telegram_account.account_type != "user":
                p.ctx.logger.warning("Telegram Bot 历史补取 unsupported：不支持 Bot API/getHistory 历史")
                return
            if self.watermarks is None:
                self.watermarks = Watermarks(p.ctx.paths.data_dir / "catchup-watermarks.sqlite3",
                                             p._self_account_id)
            self.task = asyncio.create_task(self.run())
            self.task.add_done_callback(self.done)

    def done(self, task):
        if not task.cancelled() and task.exception() is not None:
            self.bridge.plugin.ctx.logger.error("Telegram 补历史失败：%s", type(task.exception()).__name__)

    async def cancel(self):
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self):
        async with self.lock:
            await self.cancel()

    async def run(self):
        p = self.bridge.plugin
        budget = min(60.0, max(1.0, p._load_settings().catchup.time_budget_seconds))
        try:
            await asyncio.wait_for(self.fetch(), timeout=budget)
        except asyncio.TimeoutError:
            p.ctx.logger.warning("Telegram 补历史达到时间上限；未确认消息不会推进水位")

    async def fetch(self):
        p = self.bridge.plugin
        settings = p._load_settings()
        config = settings.catchup
        client = p._tg_client.client
        remaining = min(500, max(1, config.total_limit))
        for target in list(dict.fromkeys(config.targets))[:32]:
            if remaining <= 0 or self.bridge.closed:
                break
            chat, topic = parse_target(target)
            private = chat > 0
            s = p._load_settings().chat
            if not private and (not s.enable_group_chat or
                    (s.group_list_type == "whitelist" and
                     not p._chat_filter._id_matches(str(chat), list(s.group_list)))):
                continue
            # 在任何 Telegram 请求之前确认 Host 已注册的精确话题/私聊对象。
            if not await p._resolve_host_stream_id(target):
                continue
            if not p._chat_filter.check_allow(s, user_id=str(chat), chat_id=str(chat),
                    is_private=private, is_channel=False, sender_is_bot=False):
                continue
            entity = await client.get_entity(chat)
            from telethon import utils
            if utils.get_peer_id(entity) != chat:
                raise ValueError("补历史 peer 归属不匹配")
            if bool(getattr(entity, "broadcast", False)) and s.ignore_channels:
                continue
            if topic is not None and not bool(getattr(entity, "forum", False)):
                continue
            cursor = self.watermarks.read(target)
            limit = min(100, max(1, config.per_stream_limit), remaining)
            kwargs = {"limit": limit, "min_id": cursor}
            if topic is not None:
                kwargs["reply_to"] = topic
            # Telegram 默认倒序：只取最近有界窗口，再按 ID 升序 ACK/提交。
            messages = await client.get_messages(entity, **kwargs)
            remaining -= limit  # 按请求额度计费，空结果也不能放大扫描范围。
            if len(messages) >= limit:
                p.ctx.logger.warning("Telegram 补历史窗口可能截断；不是全量恢复: target=%s", target)
            for message in sorted(messages, key=lambda m: m.id):
                if self.bridge.closed:
                    return
                if int(message.id) <= cursor:
                    continue
                if message.chat_id != chat or bool(message.is_private) != private:
                    raise ValueError("补历史消息归属不匹配")
                actual_topic = None if private else p._inbound_codec._resolve_topic_thread_id(message)
                if actual_topic != topic:
                    continue
                event = SimpleNamespace(message=message, chat_id=chat, sender_id=message.sender_id,
                    sender=message.sender, is_private=private, is_group=bool(message.is_group),
                    is_channel=bool(message.is_channel))
                # 不走 NewMessage/live dispatch/Planner。拒绝、未知作者/所有权不越过水位。
                acknowledged = await self.bridge.history(event, "catchup")
                if acknowledged is not True:
                    break
                self.watermarks.advance(target, message.id)
                cursor = int(message.id)
