"""短泛化回复的跨聊天流重复防护。

目的不是用同义词替换来伪造随机性，而是避免机器人在多个聊天流中短时间重复
发送无上下文的相同短句。没有自然的新信息时，调用方应当不发。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque

import re


@dataclass(frozen=True)
class _ReplyRecord:
    chat_id: str
    text: str
    at: float


class ReplyReuseGuard:
    """保存有限窗口内的短回复，用于阻止跨聊天流精确复用。"""

    def __init__(
        self,
        *,
        window_seconds: float = 1800.0,
        same_chat_window_seconds: float = 600.0,
        max_text_length: int = 12,
    ) -> None:
        self._window_seconds = window_seconds
        self._same_chat_window_seconds = same_chat_window_seconds
        self._max_text_length = max_text_length
        self._records: Deque[_ReplyRecord] = deque()

    @staticmethod
    def _normalize(text: str) -> str:
        """按可见文本比较，忽略空白和收尾标点的无意义差异。"""

        normalized = "".join(str(text).split())
        return re.sub(r"[。.!！?？]+$", "", normalized).strip()

    def _prune(self, now: float) -> None:
        while self._records and now - self._records[0].at > self._window_seconds:
            self._records.popleft()

    def is_recent_cross_chat_duplicate(self, chat_id: str, text: str, *, now: float) -> bool:
        """仅对短文本检查其他聊天流近期是否已发送过相同内容。"""

        self._prune(now)
        normalized = self._normalize(text)
        if not normalized or len(normalized) > self._max_text_length:
            return False
        return any(
            record.chat_id != str(chat_id) and record.text == normalized
            for record in self._records
        )

    def is_recent_repeat(self, chat_id: str, text: str, *, now: float) -> bool:
        """检查同一聊天流近期是否已发送过相同的短文本。"""

        self._prune(now)
        normalized = self._normalize(text)
        if not normalized or len(normalized) > self._max_text_length:
            return False
        return any(
            record.chat_id == str(chat_id)
            and record.text == normalized
            and now - record.at <= self._same_chat_window_seconds
            for record in self._records
        )

    def record(self, chat_id: str, text: str, *, now: float) -> None:
        """记录实际已发送的文本，供后续聊天流比较。"""

        self._prune(now)
        normalized = self._normalize(text)
        if normalized and len(normalized) <= self._max_text_length:
            self._records.append(_ReplyRecord(str(chat_id), normalized, now))
