"""媒体视觉理解成本治理（升级计划 Phase 9）。

已有：
- ``image_manager`` 按 sha256 缓存视觉描述（同一媒体只识别一次）。
- 适配器 ``image_burst`` 把连发图片合并。

本模块补"是否需要看图"的低成本预判：在**没人叫我们**时，同一聊天流
短时间内只为前 N 张非指向媒体下载并交给 VLM，其余用文本占位（不下载、不识别）。
被 @/回复我们的媒体，或近期（5 分钟内）刚与我们互动过的群友发来的后续图片，
照常下载识别，避免对话中途突然"瞎眼"。
"""

from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

import time

WINDOW_SECONDS = 10 * 60
MAX_UNDIRECTED_PER_WINDOW = 4
ACTIVE_PEER_WINDOW_SECONDS = 5 * 60
MAX_ACTIVE_PEERS = 512


def normalize_budget_chat_id(chat_id: object) -> str:
    """统一会话键格式：剥离 `:topic_id` 后缀与 `-100` 超级群前缀，保证 Telethon bare channel_id 与 peer chat_id 完全一致。"""
    raw = str(chat_id or "").strip()
    if not raw:
        return ""
    head = raw.split(":", 1)[0].strip()
    if head.startswith("-100") and head[4:].isdigit():
        return head[4:]
    if head.startswith("-") and head[1:].isdigit():
        return head[1:]
    return head


class MediaBudget:
    """按会话的非指向媒体识别预算。"""

    def __init__(
        self,
        window: float = WINDOW_SECONDS,
        limit: int = MAX_UNDIRECTED_PER_WINDOW,
        active_peer_window: float = ACTIVE_PEER_WINDOW_SECONDS,
        max_active_peers: int = MAX_ACTIVE_PEERS,
    ) -> None:
        self._window = window
        self._limit = limit
        self._active_peer_window = active_peer_window
        self._max_active_peers = max(1, int(max_active_peers))
        self._seen: Dict[str, Deque[float]] = defaultdict(deque)
        self._active_peers: Dict[Tuple[str, str], float] = {}
        self.skipped = 0
        self.allowed = 0

    def _prune_active_peers(self, now: float) -> None:
        cutoff = now - self._active_peer_window
        expired = [k for k, ts in self._active_peers.items() if ts <= cutoff]
        for k in expired:
            self._active_peers.pop(k, None)
        overflow = len(self._active_peers) - self._max_active_peers
        if overflow > 0:
            for k, _ in sorted(self._active_peers.items(), key=lambda item: item[1])[:overflow]:
                self._active_peers.pop(k, None)

    def note_peer_interaction(
        self, chat_id: str, sender_id: Optional[str], *, now: Optional[float] = None
    ) -> None:
        """记录本账号在某会话刚与某位群友产生直接互动（对方 @/引用我们，或我们引用回复对方）。"""
        norm_chat = normalize_budget_chat_id(chat_id)
        norm_sender = str(sender_id or "").strip()
        if not norm_chat or not norm_sender:
            return
        ts = time.monotonic() if now is None else now
        self._active_peers[(norm_chat, norm_sender)] = ts
        self._prune_active_peers(ts)

    def is_active_peer(
        self, chat_id: str, sender_id: Optional[str], *, now: Optional[float] = None
    ) -> bool:
        """判断该发送者是否在近期活跃互动窗口内。"""
        norm_chat = normalize_budget_chat_id(chat_id)
        norm_sender = str(sender_id or "").strip()
        if not norm_chat or not norm_sender:
            return False
        ts = time.monotonic() if now is None else now
        self._prune_active_peers(ts)
        return (norm_chat, norm_sender) in self._active_peers

    def should_analyze(
        self,
        chat_id: str,
        *,
        directed_at_us: bool,
        sender_id: Optional[str] = None,
        now: Optional[float] = None,
    ) -> bool:
        norm_chat = normalize_budget_chat_id(chat_id)
        now = time.monotonic() if now is None else now
        if directed_at_us:
            if sender_id:
                self.note_peer_interaction(norm_chat, sender_id, now=now)
            self.allowed += 1
            return True
        if sender_id and self.is_active_peer(norm_chat, sender_id, now=now):
            self.allowed += 1
            return True
        queue = self._seen[norm_chat]
        while queue and now - queue[0] > self._window:
            queue.popleft()
        if len(queue) >= self._limit:
            self.skipped += 1
            return False
        queue.append(now)
        self.allowed += 1
        return True
