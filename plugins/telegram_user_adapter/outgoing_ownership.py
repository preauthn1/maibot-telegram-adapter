"""发送所有权持久账本：平台回执先于任何可失败的观察回调保存。"""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import asyncio
import logging
import sqlite3
import time
import uuid


class OutgoingOwnership:
    def __init__(self, path: Path, account_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.account_id = account_id
        self.active = 0
        self.receipt_failed = False
        self.idle = asyncio.Event()
        self.idle.set()
        self.depth = ContextVar("telegram_owned_send", default=False)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ownership_epoch(account TEXT PRIMARY KEY, started REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS owned_receipt(account TEXT, chat TEXT, mid INTEGER,
                    PRIMARY KEY(account, chat, mid));
                CREATE TABLE IF NOT EXISTS send_attempt(token TEXT PRIMARY KEY, account TEXT,
                    started REAL NOT NULL, ended REAL, state TEXT NOT NULL);
            """)
            db.execute("INSERT OR IGNORE INTO ownership_epoch VALUES (?,?)", (account_id, time.time()))
            # 上次进程中断的发送无法判断是否送达，封存为不确定时间窗。
            db.execute("UPDATE send_attempt SET ended=?, state='unknown' WHERE account=? AND state='pending'",
                       (time.time(), account_id))
        path.chmod(0o600)

    @contextmanager
    def db(self) -> Any:
        connection = sqlite3.connect(self.path, timeout=5)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    async def send(self, method: Any, *args: Any, **kwargs: Any) -> Any:
        if self.depth.get():
            return await method(*args, **kwargs)
        token = uuid.uuid4().hex
        with self.db() as db:
            db.execute("INSERT INTO send_attempt VALUES (?,?,?,NULL,'pending')",
                       (token, self.account_id, time.time()))
        self.active += 1
        self.idle.clear()
        depth_token = self.depth.set(True)
        try:
            result = await method(*args, **kwargs)
            messages = result if isinstance(result, (list, tuple)) else [result]
            try:
                if not messages:
                    raise ValueError("发送未返回可核验的平台回执")
                receipts = [(self.account_id, str(m.chat_id), int(m.id)) for m in messages]
                if any(chat == "None" or mid <= 0 for _, chat, mid in receipts):
                    raise ValueError("发送回执缺少有效的聊天或消息 ID")
                # 同步事务内保存整个多段回执，不让 update 在回执登记前穿过。
                with self.db() as db:
                    db.executemany("INSERT OR IGNORE INTO owned_receipt VALUES (?,?,?)", receipts)
                    db.execute("UPDATE send_attempt SET ended=?, state='confirmed' WHERE token=?",
                               (time.time(), token))
            except Exception:
                # 已送达绝不能变发送失败/重试。持久 pending + 本进程闭锁阻止误归类。
                self.receipt_failed = True
                logging.getLogger(__name__).error("发送已完成但所有权回执未保存；自账号历史已闭锁")
            return result
        except BaseException:
            with self.db() as db:
                db.execute("UPDATE send_attempt SET ended=?, state='unknown' WHERE token=?",
                           (time.time(), token))
            raise
        finally:
            self.depth.reset(depth_token)
            self.active -= 1
            if not self.active:
                self.idle.set()

    async def classify(self, chat: str, mid: int, timestamp: float) -> str:
        if self.receipt_failed:
            return "unknown"
        try:
            await asyncio.wait_for(self.idle.wait(), timeout=30)
        except asyncio.TimeoutError:
            return "unknown"
        # wait_for resumes separately from Event.wait: another send may have
        # cleared idle meanwhile. No await is allowed between this gate and SQL.
        if self.receipt_failed or self.active:
            return "unknown"
        with self.db() as db:
            if db.execute("SELECT 1 FROM owned_receipt WHERE account=? AND chat=? AND mid=?",
                          (self.account_id, chat, mid)).fetchone():
                return "automated"
            epoch = db.execute("SELECT started FROM ownership_epoch WHERE account=?", (self.account_id,)).fetchone()[0]
            if timestamp <= epoch:
                return "unknown"
            uncertain = db.execute("SELECT 1 FROM send_attempt WHERE account=? AND state IN ('pending','unknown') "
                                   "AND started-1<=? AND (ended IS NULL OR ended+1>=?) LIMIT 1",
                                   (self.account_id, timestamp, timestamp)).fetchone()
            return "unknown" if uncertain else "manual_account"


def ownership_client_class(base: Any) -> Any:
    """覆盖高层发送入口，包含辅助任务直接使用 client 的发送；不新增连接。"""
    class OwnedTelegramClient(base):
        outgoing_ownership = None
        history_connected_callback = None

        async def _handle_auto_reconnect(self):
            # Telethon 在已有连接上完成自动重连；不创建客户端或重新授权。
            callback = self.history_connected_callback
            if callback is not None:
                await callback()
            await super()._handle_auto_reconnect()

        async def send_message(self, *args: Any, **kwargs: Any) -> Any:
            if self.outgoing_ownership is None:
                raise RuntimeError("发送所有权账本尚未初始化")
            return await self.outgoing_ownership.send(super().send_message, *args, **kwargs)

        async def send_file(self, *args: Any, **kwargs: Any) -> Any:
            if self.outgoing_ownership is None:
                raise RuntimeError("发送所有权账本尚未初始化")
            return await self.outgoing_ownership.send(super().send_file, *args, **kwargs)

        async def forward_messages(self, *args: Any, **kwargs: Any) -> Any:
            if self.outgoing_ownership is None:
                raise RuntimeError("发送所有权账本尚未初始化")
            return await self.outgoing_ownership.send(super().forward_messages, *args, **kwargs)

    return OwnedTelegramClient
