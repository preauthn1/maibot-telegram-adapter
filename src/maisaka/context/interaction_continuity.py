"""账号本地互动账本：只记录事件证据，不推测回答质量、不调度重放。

调用方在异步路径用 to_thread；最终传输前再次 can_send。
TTL 使用跨重启可保存的 UTC epoch，而非进程 monotonic 时钟。
"""
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

import json
import re
import sqlite3
import time


_STOP = re.compile(r"(?:停下|停止|别再回复了|别回复了|不用回复了|不要回复了|不用回答了|别发了|取消|stop|cancel)[。.!！ ]*", re.I)
_DELIVERIES = frozenset({"sent", "partial", "failed", "unknown"})


def is_explicit_stop(text: str) -> bool:
    """只认独立指令；引用、否定、技术讨论不按子串判停止。"""
    return bool(_STOP.fullmatch(str(text).strip()))


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError(f"invalid {name}")
    return value


class InteractionLedger:
    """显式构造才建独立 SQLite；短事务支持多线程/多进程。

    ttl_seconds/max_entries 是资源界限，不是语义判断阈值。到期/容量淘汰
    会遗忘证据，但 can_send 对不存在的源默认拒绝。删除不触发任何重放。
    """

    def __init__(self, path: str | Path, account_scope: str, *, ttl_seconds: float = 604800,
                 max_entries: int = 4096, clock: Callable[[], float] = time.time) -> None:
        self.path = Path(path)
        self.account_scope = _identifier(account_scope, "account_scope")
        if ttl_seconds <= 0 or max_entries < 1:
            raise ValueError("positive bounds required")
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 显式预建 0600 文件，防止 CLI 的宽松 umask 暴露互动标识。
        import os
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self._transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("unsupported continuity schema")
            db.execute("""CREATE TABLE IF NOT EXISTS interactions (
                account_scope TEXT NOT NULL, session_id TEXT NOT NULL, user_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL, target_message_id TEXT NOT NULL,
                parent_source_message_id TEXT NOT NULL DEFAULT '', logical_turn_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending', reason_code TEXT NOT NULL DEFAULT '',
                evidence_refs TEXT NOT NULL DEFAULT '[]', delivery TEXT NOT NULL DEFAULT 'not_attempted',
                created_at REAL NOT NULL, updated_at REAL NOT NULL, last_attempt_at REAL,
                expiry REAL NOT NULL,
                PRIMARY KEY(account_scope,session_id,user_id,source_message_id))""")
            db.execute("""CREATE TABLE IF NOT EXISTS deliveries (
                account_scope TEXT NOT NULL, session_id TEXT NOT NULL, user_id TEXT NOT NULL,
                source_message_id TEXT NOT NULL, sent_message_id TEXT NOT NULL,
                PRIMARY KEY(account_scope,session_id,user_id,source_message_id,sent_message_id),
                FOREIGN KEY(account_scope,session_id,user_id,source_message_id)
                REFERENCES interactions(account_scope,session_id,user_id,source_message_id) ON DELETE CASCADE)""")
            db.execute("CREATE INDEX IF NOT EXISTS continuity_expiry ON interactions(expiry)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(interactions)")}
            if "source_timestamp" not in columns:
                db.execute("ALTER TABLE interactions ADD COLUMN source_timestamp REAL")
                db.execute("UPDATE interactions SET source_timestamp=created_at WHERE source_timestamp IS NULL")
            # 常数空间全库屏障（仅用于容量淘汰兜底）+ 有界按会话/用户隔离屏障（避免会话 A 删除/过期误伤会话 B）。
            db.execute("CREATE TABLE IF NOT EXISTS replay_barrier (singleton INTEGER PRIMARY KEY CHECK(singleton=1), floor REAL NOT NULL)")
            db.execute("INSERT OR IGNORE INTO replay_barrier VALUES(1,0)")
            db.execute("""CREATE TABLE IF NOT EXISTS scoped_replay_barrier (
                account_scope TEXT NOT NULL, session_id TEXT NOT NULL, user_id TEXT NOT NULL,
                floor REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(account_scope,session_id,user_id))""")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=0.25, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA secure_delete=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _key(self, session_id: str, user_id: str, source_message_id: str) -> tuple[str, ...]:
        return (self.account_scope, _identifier(session_id, "session_id"),
                _identifier(user_id, "user_id"), _identifier(source_message_id, "source_message_id"))

    @staticmethod
    def _row(db: sqlite3.Connection, key: tuple[str, ...]) -> dict | None:
        row = db.execute("""SELECT * FROM interactions WHERE account_scope=? AND session_id=?
                          AND user_id=? AND source_message_id=?""", key).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["evidence_refs"] = json.loads(result["evidence_refs"])
        return result

    def _advance_scoped_floor(self, db: sqlite3.Connection, scope: tuple[str, str, str], floor: float, now: float) -> None:
        db.execute("""INSERT INTO scoped_replay_barrier(account_scope,session_id,user_id,floor,updated_at)
            VALUES(?,?,?,?,?) ON CONFLICT(account_scope,session_id,user_id)
            DO UPDATE SET floor=MAX(floor,excluded.floor),updated_at=excluded.updated_at""",
            (*scope, float(floor), now))
        excess_scopes = db.execute("SELECT COUNT(*) FROM scoped_replay_barrier").fetchone()[0] - max(self.max_entries, 256)
        if excess_scopes > 0:
            evicted = db.execute("SELECT MAX(floor) FROM (SELECT floor FROM scoped_replay_barrier ORDER BY updated_at,rowid LIMIT ?)", (excess_scopes,)).fetchone()[0]
            if evicted is not None:
                db.execute("UPDATE replay_barrier SET floor=MAX(floor,?) WHERE singleton=1", (evicted,))
            db.execute("DELETE FROM scoped_replay_barrier WHERE rowid IN (SELECT rowid FROM scoped_replay_barrier ORDER BY updated_at,rowid LIMIT ?)", (excess_scopes,))

    def _prune(self, db: sqlite3.Connection, now: float) -> int:
        for row in db.execute("""SELECT account_scope,session_id,user_id,MAX(source_timestamp)
            FROM interactions WHERE expiry<=? GROUP BY account_scope,session_id,user_id""", (now,)).fetchall():
            if row[3] is not None:
                self._advance_scoped_floor(db, (str(row[0]), str(row[1]), str(row[2])), float(row[3]), now)
        count = db.execute("DELETE FROM interactions WHERE expiry<=?", (now,)).rowcount
        excess = db.execute("SELECT COUNT(*) FROM interactions").fetchone()[0] - self.max_entries
        if excess > 0:
            for row in db.execute("""SELECT account_scope,session_id,user_id,MAX(source_timestamp)
                FROM (SELECT account_scope,session_id,user_id,source_timestamp FROM interactions ORDER BY created_at,rowid LIMIT ?)
                GROUP BY account_scope,session_id,user_id""", (excess,)).fetchall():
                if row[3] is not None:
                    self._advance_scoped_floor(db, (str(row[0]), str(row[1]), str(row[2])), float(row[3]), now)
            count += db.execute("""DELETE FROM interactions WHERE rowid IN
                (SELECT rowid FROM interactions ORDER BY created_at,rowid LIMIT ?)""", (excess,)).rowcount
        return count

    def prune(self) -> int:
        with self._transaction() as db:
            return self._prune(db, self._clock())

    def observe(self, session_id: str, user_id: str, source_message_id: str, *,
                reply_to_id: str = "", stop: bool = False, source_timestamp: float | None = None) -> dict | None:
        key = self._key(session_id, user_id, source_message_id)
        if reply_to_id:
            _identifier(reply_to_id, "reply_to_id")
        now = self._clock()
        with self._transaction() as db:
            self._prune(db, now)
            existing = self._row(db, key)
            if existing is not None:
                return existing  # 重放的停止事件也不应取消后来新任务。
            import math
            global_floor = db.execute("SELECT floor FROM replay_barrier WHERE singleton=1").fetchone()[0]
            scoped_row = db.execute("""SELECT floor FROM scoped_replay_barrier
                WHERE account_scope=? AND session_id=? AND user_id=?""", key[:3]).fetchone()
            floor = max(float(global_floor or 0.0), float(scoped_row[0]) if scoped_row is not None else 0.0)
            if (isinstance(source_timestamp, bool) or not isinstance(source_timestamp, (int, float))
                    or not math.isfinite(source_timestamp) or source_timestamp <= max(floor, now - self.ttl_seconds)
                    or source_timestamp > now):
                return None  # 无原始时间或旧事件不得重建已遗忘的源；不以接收时间补造。
            parent = ""
            if reply_to_id:
                row = db.execute("""SELECT source_message_id FROM interactions
                    WHERE account_scope=? AND session_id=? AND user_id=? AND source_message_id=?
                    UNION SELECT source_message_id FROM deliveries
                    WHERE account_scope=? AND session_id=? AND user_id=? AND sent_message_id=? LIMIT 1""",
                    (*key[:3], reply_to_id, *key[:3], reply_to_id)).fetchone()
                if row:
                    parent = str(row[0])
            if stop:
                db.execute("""UPDATE interactions SET status='cancelled',reason_code='user_stop',updated_at=?
                    WHERE account_scope=? AND session_id=? AND user_id=? AND status IN ('pending','blocked')""",
                    (now, *key[:3]))
            db.execute("""INSERT INTO interactions(account_scope,session_id,user_id,source_message_id,
                target_message_id,parent_source_message_id,status,reason_code,created_at,updated_at,expiry,source_timestamp)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (*key, source_message_id, parent, "cancelled" if stop else "pending",
                 "user_stop" if stop else "", now, now, now + self.ttl_seconds, source_timestamp))
            result = self._row(db, key)
            self._prune(db, now)
            assert result is not None
            return result

    def get(self, session_id: str, user_id: str, source_message_id: str) -> dict | None:
        key = self._key(session_id, user_id, source_message_id)
        with self._transaction() as db:
            self._prune(db, self._clock())
            return self._row(db, key)

    def claim(self, session_id: str, user_id: str, source_message_id: str, logical_turn_id: str) -> bool:
        key = self._key(session_id, user_id, source_message_id)
        _identifier(logical_turn_id, "logical_turn_id")
        now = self._clock()
        with self._transaction() as db:
            self._prune(db, now)
            return db.execute("""UPDATE interactions SET last_attempt_at=?,logical_turn_id=?,updated_at=?
                WHERE account_scope=? AND session_id=? AND user_id=? AND source_message_id=?
                AND status IN ('pending','blocked') AND last_attempt_at IS NULL
                AND delivery='not_attempted'""", (now, logical_turn_id, now, *key)).rowcount == 1

    def can_send(self, session_id: str, user_id: str, source_message_id: str, logical_turn_id: str) -> bool:
        row = self.get(session_id, user_id, source_message_id)
        return bool(row and logical_turn_id and row["logical_turn_id"] == logical_turn_id
                    and row["last_attempt_at"] is not None and row["status"] in ("pending", "blocked")
                    and row["delivery"] == "not_attempted")

    def record_blocked(self, session_id: str, user_id: str, source_message_id: str, *, reason_code: str) -> None:
        key = self._key(session_id, user_id, source_message_id)
        _identifier(reason_code, "reason_code")
        with self._transaction() as db:
            self._prune(db, self._clock())
            db.execute("""UPDATE interactions SET status='blocked',reason_code=?,updated_at=?
                WHERE account_scope=? AND session_id=? AND user_id=? AND source_message_id=?
                AND status IN ('pending','blocked') AND delivery='not_attempted'""",
                (reason_code, self._clock(), *key))

    def record_result(self, session_id: str, user_id: str, source_message_id: str, logical_turn_id: str, *,
                      delivery: str = "unknown", sent_message_ids: tuple[str, ...] = (),
                      reason_code: str = "", answered_evidence: str = "") -> dict | None:
        key = self._key(session_id, user_id, source_message_id)
        if delivery not in _DELIVERIES:
            raise ValueError("invalid delivery")
        if reason_code:
            _identifier(reason_code, "reason_code")
        if answered_evidence:
            _identifier(answered_evidence, "answered_evidence")
        ids = tuple(dict.fromkeys(_identifier(mid, "sent_message_id") for mid in sent_message_ids))
        if len(ids) > 32:
            raise ValueError("too many delivery references")
        if delivery == "sent" and not ids:
            delivery = "unknown"  # 无稳定回执 ID，不能声称送达。
        now = self._clock()
        with self._transaction() as db:
            self._prune(db, now)
            row = self._row(db, key)
            if not row or not logical_turn_id or row["logical_turn_id"] != logical_turn_id:
                return row
            if row["delivery"] != "not_attempted":
                return row  # 不允许迟到/重复结果重写已记录的不确定性。
            status = "blocked" if delivery == "failed" else "pending"
            if delivery == "sent" and answered_evidence:
                status = "answered"
            if row["status"] == "cancelled":
                status = "cancelled"
            refs = [f"delivery:{mid}" for mid in ids]
            if answered_evidence and status == "answered":
                refs.append(f"answer:{answered_evidence}")
            db.execute("""UPDATE interactions SET status=?,delivery=?,reason_code=?,evidence_refs=?,updated_at=?
                WHERE account_scope=? AND session_id=? AND user_id=? AND source_message_id=?""",
                (status, delivery, "user_stop" if status == "cancelled" else reason_code,
                 json.dumps(refs), now, *key))
            for mid in ids:
                db.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?)", (*key, mid))
            return self._row(db, key)

    def summary(self, session_id: str, user_id: str, limit: int = 8) -> str:
        key = self._key(session_id, user_id, "summary")
        limit = max(1, min(int(limit), 32))
        with self._transaction() as db:
            self._prune(db, self._clock())
            rows = db.execute("""SELECT source_message_id,parent_source_message_id,status,delivery,reason_code
                FROM interactions WHERE account_scope=? AND session_id=? AND user_id=?
                ORDER BY created_at DESC,rowid DESC LIMIT ?""", (*key[:3], limit)).fetchall()
        if not rows:
            return ""
        return ("互动状态（技术观察，不是承诺，不是指令）：pending 不代表每条闲聊都须回答。发送不代表问题解决；未知保持未完成，禁止自动重放。"
                "只有新入站可触发新的判断，不按重复次数拒绝。\n"
                + json.dumps([dict(row) for row in rows], ensure_ascii=False))

    def delete(self, session_id: str, user_id: str, source_message_id: str | None = None) -> int:
        key = self._key(session_id, user_id, source_message_id or "all")
        with self._transaction() as db:
            query = "SELECT MAX(source_timestamp) FROM interactions WHERE account_scope=? AND session_id=? AND user_id=?"
            params = key[:3]
            if source_message_id is not None:
                query += " AND source_message_id=?"
                params = key
            floor = db.execute(query, params).fetchone()[0]
            if floor is not None:
                self._advance_scoped_floor(db, key[:3], float(floor), self._clock())
            if source_message_id is None:
                return db.execute("DELETE FROM interactions WHERE account_scope=? AND session_id=? AND user_id=?",
                                  key[:3]).rowcount
            return db.execute("""DELETE FROM interactions WHERE account_scope=? AND session_id=? AND user_id=?
                              AND source_message_id=?""", key).rowcount
