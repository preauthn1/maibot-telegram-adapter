"""消息漏斗追踪（升级计划 Phase 0.2 / Phase 1.2）。

目的：回答"这条为什么没回复"——是适配器哪道闸门拦了、Planner 没选，
还是平台发失败。此前只有零散日志，且常把"回复器生成成功"误当出站证据。

每个阶段写一行 JSON 到 ``funnel/YYYY-MM-DD.jsonl``（Asia/Shanghai 日期）：

- ``inbound_pass``：适配器在路由前丢弃，附唯一 ``reason``（PASS 原因）。
- ``inbound_routed``：已交给 Host（之后由 Planner 决定说不说）。
- ``outbound_blocked``：出站闸门拦截（权限、话语权、连续发言、管人话术等）。
- ``platform_success`` / ``platform_failure``：平台真实结果，含段数与错误类型。

只记 ID/原因/计数，不记正文，避免把群聊内容二次落盘。
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import json
import threading
import time

_CN_TZ = timezone(timedelta(hours=8))

# 统一 PASS 原因词表：调参只按这些原因统计，不凭感觉改阈值。
PASS_REASONS = {
    "quiet_hours",
    "presence_offline",
    "permission_blocked",
    "not_whitelisted",
    "spam",
    "nsfw",
    "image_burst",
    "user_flood",
    "provocation_cooldown",
    "burst_in_progress",
    "topic_not_for_bot",
    "trigger_skip",
    "small_chat_suppressed",
    "closing_signal",
    "bystander",
    "duplicate_joke",
    "low_information",
    "convert_failed",
}


class FunnelLog:
    """线程安全的漏斗事件追加写入器。"""

    def __init__(self, base_dir: Optional[Path]) -> None:
        self._base = base_dir
        self._lock = threading.Lock()

    def record(self, stage: str, chat_id: str, **fields: Any) -> None:
        """追加一条漏斗事件。

        Args:
            stage: 阶段名。
            chat_id: 会话 ID。
            **fields: 附加字段（只放 ID、原因、计数）。
        """

        if self._base is None:
            return
        # PASS 原因词表由 scripts/verify_funnel_reasons.py 静态校验（调用点全是字面量），
        # 不在消息处理热路径里抛异常，避免一个拼写错误中断整条入站链路。
        now = datetime.now(_CN_TZ)
        row: Dict[str, Any] = {"ts": now.isoformat(timespec="seconds"), "unix": round(time.time(), 3), "stage": stage, "chat_id": str(chat_id)}
        row.update(fields)
        path = self._base / f"{now:%Y-%m-%d}.jsonl"
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
