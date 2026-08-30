"""结构化聊天记录日志。

目的（需求 2）：事后审查"这段对话看起来像不像真人"。

因此日志不仅记录消息内容，还记录**拟人化决策过程**：
- 每条出站消息的排队等待、打字时长、实际发送耗时；
- 身份守卫和拟人化改写是否介入、改了什么；
- 消息是否因静默时段被丢弃；
- 从收到消息到发出回复的端到端延迟（真人的响应延迟分布是关键特征）。

每个聊天一个 JSONL 文件，按 chat_id 分开存放，便于单独审查某个群。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import asyncio
import json
import re

_CN_TZ = timezone(timedelta(hours=8))

# 文件名安全化：chat_id 可能带负号，也可能是虚拟 topic id。
_UNSAFE_FILENAME_CHARS = re.compile(r"[^0-9A-Za-z_.-]")


class ChatTranscriptLogger:
    """把收发消息与拟人化决策写入 JSONL。"""

    def __init__(self, log_dir: Path, logger: Any, *, enabled: bool = True) -> None:
        """初始化聊天记录日志器。

        Args:
            log_dir: 日志根目录。
            logger: 插件日志器。
            enabled: 是否启用记录。
        """

        self._log_dir = log_dir
        self._logger = logger
        self._enabled = enabled
        self._lock = asyncio.Lock()

        if self._enabled:
            try:
                self._log_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._logger.warning(f"无法创建聊天日志目录 {self._log_dir}: {exc}")
                self._enabled = False

    @property
    def enabled(self) -> bool:
        """返回日志功能是否可用。

        Returns:
            bool: 可用返回 ``True``。
        """

        return self._enabled

    def _resolve_path(self, chat_id: str) -> Path:
        """计算某个聊天的日志文件路径。

        Args:
            chat_id: 聊天 ID（可能是虚拟 topic id）。

        Returns:
            Path: JSONL 文件路径。
        """

        safe = _UNSAFE_FILENAME_CHARS.sub("_", str(chat_id))[:80] or "unknown"
        return self._log_dir / f"chat_{safe}.jsonl"

    async def _write(self, chat_id: str, record: Dict[str, Any]) -> None:
        """把一条记录追加写入对应文件。

        Args:
            chat_id: 聊天 ID。
            record: 记录内容。
        """

        if not self._enabled:
            return

        record.setdefault("ts", datetime.now(_CN_TZ).isoformat())
        line = json.dumps(record, ensure_ascii=False)

        async with self._lock:
            try:
                path = self._resolve_path(chat_id)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError as exc:
                self._logger.warning(f"写入聊天日志失败 chat_id={chat_id}: {exc}")

    async def log_inbound(
        self,
        *,
        chat_id: str,
        chat_title: str,
        is_private: bool,
        sender_id: str,
        sender_name: str,
        message_id: Any,
        text: str,
        is_mention: bool,
        has_media: bool,
    ) -> None:
        """记录一条收到的消息。

        Args:
            chat_id: 聊天 ID。
            chat_title: 群名或对话名。
            is_private: 是否私聊。
            sender_id: 发送者 ID。
            sender_name: 发送者昵称。
            message_id: 消息 ID。
            text: 文本内容。
            is_mention: 是否 @ 或回复了本账号。
            has_media: 是否含媒体。
        """

        await self._write(
            chat_id,
            {
                "direction": "in",
                "chat_id": chat_id,
                "chat_title": chat_title,
                "is_private": is_private,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "message_id": message_id,
                "text": text,
                "is_mention": is_mention,
                "has_media": has_media,
            },
        )

    async def log_outbound(
        self,
        *,
        chat_id: str,
        message_id: Any,
        text: str,
        original_text: str,
        queue_wait_seconds: float,
        typing_seconds: float,
        reply_latency_seconds: Optional[float],
        priority: int,
        humanize_rules: Optional[list[str]] = None,
        identity_guard_triggered: bool = False,
        reply_is_quote: bool = False,
    ) -> None:
        """记录一条已发出的消息及其拟人化决策。

        Args:
            chat_id: 聊天 ID。
            message_id: Telegram 返回的消息 ID。
            text: 实际发出的文本。
            original_text: 拟人化处理前的文本。
            queue_wait_seconds: 在发送队列中的等待时长。
            typing_seconds: 模拟打字时长。
            reply_latency_seconds: 从收到对方消息到发出回复的总时长。
            priority: 队列优先级。
            humanize_rules: 命中的拟人化规则。
            identity_guard_triggered: 身份守卫是否介入。
        """

        await self._write(
            chat_id,
            {
                "direction": "out",
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "rewritten": text != original_text,
                "original_text": original_text if text != original_text else None,
                "queue_wait_seconds": round(queue_wait_seconds, 2),
                "typing_seconds": round(typing_seconds, 2),
                "reply_latency_seconds": (
                    round(reply_latency_seconds, 2) if reply_latency_seconds is not None else None
                ),
                "priority": priority,
                "humanize_rules": humanize_rules or [],
                "identity_guard_triggered": identity_guard_triggered,
                # 是否带引用。用于验证引用降频是否真的生效——
                # 条条引用是机器人最明显的特征之一。
                "reply_is_quote": reply_is_quote,
            },
        )

    async def log_event(self, chat_id: str, event: str, detail: Dict[str, Any]) -> None:
        """记录一条非消息事件（丢弃、错误、静默等）。

        Args:
            chat_id: 聊天 ID。
            event: 事件名。
            detail: 事件细节。
        """

        await self._write(
            chat_id,
            {
                "direction": "event",
                "chat_id": chat_id,
                "event": event,
                "detail": detail,
            },
        )
