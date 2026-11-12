"""睡眠/休息期留言积压与醒后自然补看（对标 companion_v2/role_work/life/rest_gate.py）。

设计原则：
1. 休息时段（03:00–09:00 `PresenceSchedule` 离线期）内不调用任何 Telegram API（不调 `get_sender`、不发 `mark_read`），
   仅从内存中 `event.message` 已携带的轻量字段提取文本，避免把账号在线状态续期 5 分钟。
2. 对休息期间到达的白名单私聊或群内直接提及（`@`）消息，按会话记录在持久化账本 `rest_backlog.json` 中（每会话最多保留 4 条，单条最长 180 字）。
3. 醒来后（在线时段恢复）该会话首次互动时，一次性弹出积压记录，通过 `maisaka.context.append` 注入醒后补看上下文块，指导模型以“刚醒来/刚上线看到留言”自然承接，不假装半夜已回，也不丢失对方夜间的留言。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os
import tempfile

_CN_TZ = timezone(timedelta(hours=8))
MAX_BACKLOG_PER_SESSION = 4
MAX_TEXT_CHARS = 180
MAX_AGE_SECONDS = 18 * 3600.0  # 超过 18 小时的陈旧积压自动丢弃

BACKLOG_INSTRUCTION = (
    "[夜间休息期间未回留言补看]\n"
    "以下是你在休息/离线期间收到、当时尚未回复的消息（按到达顺序列出），仅作醒来/上线后的补看材料：\n"
    "不要声称当时已经回过，不要把整段休息说成没收到消息，也不要把同一件事当成全新请求重复索取信息；可结合当前新消息自然顺带回应。"
)


class RestBacklogStore:
    """持久化管理休息期间未回复的私聊与直接提及消息。"""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._items: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        for key, entries in raw.items():
            if isinstance(entries, list):
                valid = [e for e in entries if isinstance(e, dict) and isinstance(e.get("text"), str)]
                if valid:
                    self._items[str(key)] = valid[-MAX_BACKLOG_PER_SESSION:]

    def _flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=str(self._path.parent), prefix=".rest-backlog-")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self._items, handle, ensure_ascii=False)
                os.replace(tmp_name, self._path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        except OSError:
            pass

    def record(
        self,
        session_key: str,
        *,
        sender_id: str,
        text: str,
        message_id: Any = None,
        timestamp: Optional[float] = None,
    ) -> bool:
        """记录一条休息期间收到的有效文本消息（零网络 IO）。"""
        cleaned = " ".join((text or "").split()).strip()
        if not cleaned:
            return False
        if len(cleaned) > MAX_TEXT_CHARS:
            cleaned = cleaned[: MAX_TEXT_CHARS - 1] + "…"
        now_ts = datetime.now(_CN_TZ).timestamp() if timestamp is None else float(timestamp)
        time_str = datetime.fromtimestamp(now_ts, _CN_TZ).strftime("%H:%M")
        bucket = self._items.setdefault(str(session_key), [])
        mid_str = str(message_id or "")
        if mid_str and any(str(item.get("message_id") or "") == mid_str for item in bucket):
            return False
        bucket.append(
            {
                "sender_id": str(sender_id),
                "text": cleaned,
                "message_id": mid_str,
                "ts": now_ts,
                "time_str": time_str,
            }
        )
        if len(bucket) > MAX_BACKLOG_PER_SESSION:
            del bucket[:-MAX_BACKLOG_PER_SESSION]
        self._flush()
        return True

    def pop_for_session(self, session_key: str, *, now_ts: Optional[float] = None) -> str:
        """弹出并格式化指定会话的未过期积压消息；无积压时返回空串。"""
        key = str(session_key)
        entries = self._items.pop(key, None)
        if not entries:
            return ""
        self._flush()
        current = datetime.now(_CN_TZ).timestamp() if now_ts is None else float(now_ts)
        fresh = [
            item
            for item in entries
            if (current - float(item.get("ts") or 0.0)) <= MAX_AGE_SECONDS and item.get("text")
        ]
        if not fresh:
            return ""
        lines = [BACKLOG_INSTRUCTION]
        for idx, item in enumerate(fresh, start=1):
            t_label = item.get("time_str") or "休息期"
            mid_label = f" (msg_id={item['message_id']})" if item.get("message_id") else ""
            lines.append(f"{idx}. [{t_label} sender={item.get('sender_id', '')}{mid_label}] {item['text']}")
        return "\n".join(lines)
