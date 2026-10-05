"""Telegram 会话发言权限状态机（升级计划 Phase 0.1）。

背景：此前所有发送失败都被归成"无发言权限"，一刀切静默 6 小时，
既无法区分 FloodWait（Telegram 明确告诉了要等多久）、禁言（可恢复）、
被踢/私有频道（长期不可用）和网络抖动（与权限无关），
也无法在权限恢复后自动恢复；10-01~10-03 日志里 256 次
``You can't write in this chat`` 与 376 条入站冷却丢弃都来自这一层。

本模块按会话维护状态并持久化：

- ``healthy``：正常。
- ``write_forbidden``：被禁言/无发言权限；停止生成，按指数退避低频探测。
- ``private_or_banned``：被踢、私有频道、被封；长期禁用，需人工复核。
- ``flood_wait``：按 Telegram 给出的 retry_after 退避，到期自动恢复。
- ``network_error``：网络/连接失败；不影响权限判定，不阻断生成。
- ``unknown``：无法分类的失败；只记录，不阻断。

时间约定：持久化使用 Unix 时间戳（墙上时间，跨重启可用）；
判断"是否到期"只与持久化时间比较，不混用单调时钟。
"""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import json
import re
import threading
import time

HEALTHY = "healthy"
WRITE_FORBIDDEN = "write_forbidden"
PRIVATE_OR_BANNED = "private_or_banned"
FLOOD_WAIT = "flood_wait"
NETWORK_ERROR = "network_error"
UNKNOWN = "unknown"

# 会阻断"生成+排队"的状态。network_error/unknown 不阻断：
# 它们与账号在群里的权限无关，阻断会把一次抖动放大成长时间失声。
_BLOCKING_STATES = {WRITE_FORBIDDEN, PRIVATE_OR_BANNED, FLOOD_WAIT}

# 禁言探测退避：第 n 次连续确认禁言后，等待 base * 2**(n-1)，封顶 cap。
_WRITE_FORBIDDEN_BASE_SECONDS = 30 * 60
_WRITE_FORBIDDEN_CAP_SECONDS = 12 * 3600
# 被踢/私有频道：长期禁用，每 7 天才允许一次探测（仍需人工复核为主）。
_PRIVATE_PROBE_SECONDS = 7 * 24 * 3600
# FloodWait 没解析到秒数时的保守等待。
_FLOOD_DEFAULT_SECONDS = 300

_PRIVATE_MARKERS = (
    "ChannelPrivate",
    "CHANNEL_PRIVATE",
    "The channel specified is private",
    "you were banned",
    "UserBannedInChannel",
    "USER_BANNED_IN_CHANNEL",
    "UserKicked",
    "USER_KICKED",
    "ChatIdInvalid",
    "CHAT_ID_INVALID",
    "PeerIdInvalid",
    "Could not find the input entity",
)
_WRITE_FORBIDDEN_MARKERS = (
    "You can't write in this chat",
    "ChatWriteForbidden",
    "CHAT_WRITE_FORBIDDEN",
    "ChatRestricted",
    "CHAT_RESTRICTED",
    "ChatSendPlainForbidden",
    "CHAT_SEND_PLAIN_FORBIDDEN",
    "ChatAdminRequired",
    "CHAT_ADMIN_REQUIRED",
)
_FLOOD_MARKERS = ("FloodWait", "FLOOD_WAIT", "SlowModeWait", "SLOWMODE_WAIT", "A wait of")
_NETWORK_MARKERS = (
    "ConnectionError",
    "Connection reset",
    "TimeoutError",
    "timed out",
    "Server closed the connection",
    "Cannot send requests while disconnected",
    "RpcCallFail",
    "ServerError",
    "Network is unreachable",
)
_SECONDS_RE = re.compile(r"(?:A wait of|FLOOD_WAIT_|SLOWMODE_WAIT_)\s*(\d+)")


def classify_error(error: Any) -> Tuple[str, Optional[int]]:
    """把一次发送失败归类为唯一错误类型。

    优先使用 Telethon 异常对象（类型名与 ``seconds`` 属性最可靠），
    退化到错误文本匹配（outbound 层会把异常拼成字符串）。

    Args:
        error: 异常对象或错误文本。

    Returns:
        Tuple[str, Optional[int]]: (状态, retry_after 秒数)。
    """

    if error is None:
        return UNKNOWN, None
    type_name = "" if isinstance(error, str) else type(error).__name__
    text = f"{type_name}: {error}" if type_name else str(error)

    seconds_attr = getattr(error, "seconds", None)
    if any(marker in text for marker in _FLOOD_MARKERS):
        if isinstance(seconds_attr, int) and seconds_attr > 0:
            return FLOOD_WAIT, seconds_attr
        match = _SECONDS_RE.search(text)
        return FLOOD_WAIT, int(match.group(1)) if match else _FLOOD_DEFAULT_SECONDS
    # 私有/被踢必须先于"不能发言"判断：被踢的群也可能返回写入错误。
    if any(marker in text for marker in _PRIVATE_MARKERS):
        return PRIVATE_OR_BANNED, None
    if any(marker in text for marker in _WRITE_FORBIDDEN_MARKERS):
        return WRITE_FORBIDDEN, None
    if any(marker in text for marker in _NETWORK_MARKERS):
        return NETWORK_ERROR, None
    return UNKNOWN, None


@dataclass
class ChatPermission:
    """单个会话的权限状态快照。"""

    chat_id: str
    state: str = HEALTHY
    error_type: str = ""
    last_error: str = ""
    retry_after: Optional[int] = None
    first_seen: float = 0.0
    last_seen: float = 0.0
    next_probe_at: float = 0.0
    consecutive: int = 0
    last_success_at: float = 0.0
    history: list = field(default_factory=list)


class PermissionStateStore:
    """按会话维护发言权限状态，并持久化到插件数据目录。"""

    _HISTORY_LIMIT = 20

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._path = storage_path
        self._lock = threading.Lock()
        self._chats: Dict[str, ChatPermission] = {}
        self._load()

    # ---------- 持久化 ----------
    def _load(self) -> None:
        if self._path is None or not self._path.is_file():
            return
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        for chat_id, payload in raw.get("chats", {}).items():
            self._chats[chat_id] = ChatPermission(**payload)

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        payload = {"version": 1, "chats": {k: asdict(v) for k, v in self._chats.items()}}
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # ---------- 查询 ----------
    def get(self, chat_id: str) -> ChatPermission:
        return self._chats.get(str(chat_id)) or ChatPermission(chat_id=str(chat_id))

    def blocks_generation(self, chat_id: str, now: Optional[float] = None) -> bool:
        """该会话此刻是否应停止生成与排队。

        到达 ``next_probe_at`` 后返回 ``False``，放行一次真实发送作为探测；
        探测成功会恢复 healthy，失败会以更长的退避重新阻断。

        Args:
            chat_id: 会话 ID。
            now: 当前 Unix 时间，默认取系统时间。

        Returns:
            bool: 需要阻断时返回 ``True``。
        """

        record = self._chats.get(str(chat_id))
        if record is None or record.state not in _BLOCKING_STATES:
            return False
        current = time.time() if now is None else now
        return current < record.next_probe_at

    # ---------- 状态迁移 ----------
    def record_failure(self, chat_id: str, error: Any, now: Optional[float] = None) -> ChatPermission:
        """记录一次平台发送失败并迁移状态。

        Args:
            chat_id: 会话 ID。
            error: 异常对象或错误文本。
            now: 当前 Unix 时间。

        Returns:
            ChatPermission: 迁移后的状态。
        """

        current = time.time() if now is None else now
        state, retry_after = classify_error(error)
        key = str(chat_id)
        with self._lock:
            record = self._chats.get(key) or ChatPermission(chat_id=key)
            if record.state != state or record.first_seen == 0.0:
                record.first_seen = current
                record.consecutive = 0
            record.state = state
            record.error_type = state
            record.last_error = str(error)[:300]
            record.retry_after = retry_after
            record.last_seen = current
            record.consecutive += 1
            if state == FLOOD_WAIT:
                record.next_probe_at = current + float(retry_after or _FLOOD_DEFAULT_SECONDS)
            elif state == WRITE_FORBIDDEN:
                backoff = min(
                    _WRITE_FORBIDDEN_BASE_SECONDS * (2 ** (record.consecutive - 1)),
                    _WRITE_FORBIDDEN_CAP_SECONDS,
                )
                record.next_probe_at = current + backoff
            elif state == PRIVATE_OR_BANNED:
                record.next_probe_at = current + _PRIVATE_PROBE_SECONDS
            else:
                record.next_probe_at = 0.0
            record.history = (record.history + [{"at": current, "state": state, "error": record.last_error[:120]}])[
                -self._HISTORY_LIMIT :
            ]
            self._chats[key] = record
            self._save()
            return record

    def record_success(self, chat_id: str, now: Optional[float] = None) -> Optional[str]:
        """记录一次平台确认的成功发送。

        Args:
            chat_id: 会话 ID。
            now: 当前 Unix 时间。

        Returns:
            Optional[str]: 若此次成功让会话从异常状态恢复，返回原状态；否则 ``None``。
        """

        current = time.time() if now is None else now
        key = str(chat_id)
        with self._lock:
            record = self._chats.get(key)
            if record is None:
                record = ChatPermission(chat_id=key, last_success_at=current)
                self._chats[key] = record
                self._save()
                return None
            recovered_from = record.state if record.state != HEALTHY else None
            record.state = HEALTHY
            record.error_type = ""
            record.retry_after = None
            record.next_probe_at = 0.0
            record.consecutive = 0
            record.last_success_at = current
            if recovered_from:
                record.history = (record.history + [{"at": current, "state": HEALTHY, "error": ""}])[
                    -self._HISTORY_LIMIT :
                ]
            self._save()
            return recovered_from

    def reset(self, chat_id: str) -> None:
        """人工复核后清除某会话状态。"""

        with self._lock:
            if self._chats.pop(str(chat_id), None) is not None:
                self._save()

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        """导出全部会话状态，供 WebUI/排查。"""

        return {k: asdict(v) for k, v in self._chats.items()}
