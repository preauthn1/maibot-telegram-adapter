"""用户纠正账本（升级计划 Phase 8.2）。

把"不是这个意思 / 我说的是… / 别这么说 / 用户改写我们的表达"作为高价值
学习信号记下来，但**先进入待审核**，不直接改变全局风格。

按 scope 分开存：每个聊天流一个文件（群/私聊天然隔离），条目带用户别名。
只存纠正文本前 200 字与时间；不存我方原文以外的上下文，便于人工审核与清理。

读取出口（agi_discussion §2.1 下一步1）：
- 每条记录带 ``approved`` 字段，写入时恒为 False；**未经人工确认的条目绝不生效**。
- ``approved_correction_experiences`` 只导出 ``approved is True`` 的条目，转成
  ``{"kind": "correction", "text": ...}`` 会话级经验，由 ``chat_experience`` 注入 replyer。
- 导出文本只表达"避免/别再这么说"，不产生任何提高发言倾向的内容。
- 审核者确认时可选填 ``avoid_text``（我方说错的那句话），有则优先用它描述要避免的说法。

TODO（不在本次范围）：
- 确认/驳回入口（WebUI 列表或命令行脚本）。确认时应同时写 ``approved=True`` 与
  ``status="approved"``，驳回写 ``status="rejected"``；当前代码库没有任何写 approved 的入口。
- 账本按行覆写、没有条目 ID；做确认入口时需要补稳定 ID，避免按行号确认时错位。
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

import hashlib
import json
import threading

CN_TZ = timezone(timedelta(hours=8))
_ROOT = Path(__file__).resolve().parents[3] / "data" / "maisaka_state" / "corrections"
_LOCK = threading.Lock()
_MAX_PER_FILE = 500


def _scope_file(session_id: str) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return _ROOT / f"{digest}.jsonl"


def record_correction(session_id: str, *, user_id: str, text: str, kind: str = "correction") -> None:
    """追加一条待审核纠正记录。"""

    entry = {
        "at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "scope": "chat",
        "session_id": session_id,
        "user": hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:10],
        "kind": kind,
        "text": (text or "")[:200],
        "status": "pending_review",
        # 人工确认标志：只有审核入口能把它改成 True，写入时一律 False
        "approved": False,
    }
    path = _scope_file(session_id)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        lines.append(json.dumps(entry, ensure_ascii=False))
        path.write_text("\n".join(lines[-_MAX_PER_FILE:]) + "\n", encoding="utf-8")
        path.chmod(0o600)


def _read_rows(session_id: str) -> list:
    """读取某聊天流的全部账本记录；文件损坏时直接抛出，由调用方决定如何暴露。"""

    path = _scope_file(session_id)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pending_corrections(session_id: str, limit: int = 20) -> list:
    """读取某聊天流的待审核纠正（供 WebUI/人工审核）。"""

    rows = _read_rows(session_id)
    return [row for row in rows if row.get("status") == "pending_review" and row.get("approved") is not True][-limit:]


def approved_correction_experiences(session_id: str, limit: int = 5) -> List[Dict[str, str]]:
    """把已人工确认的纠正导出为会话级"避免类"经验（只读）。

    Args:
        session_id: 聊天流 ID，只读取该会话自己的账本，不跨会话。
        limit: 最多导出的条数（取最近的若干条）。

    Returns:
        List[Dict[str, str]]: ``{"kind": "correction", "text": ...}`` 列表，按时间从旧到新。
    """

    experiences: List[Dict[str, str]] = []
    for row in _read_rows(session_id):
        # 严格比较 True：缺字段、字符串 "true" 等都不算确认
        if row.get("approved") is not True or row.get("status") == "rejected":
            continue
        avoid_text = row.get("avoid_text")
        correction_text = row.get("text")
        if isinstance(avoid_text, str) and avoid_text.strip():
            text = f"在本会话说过「{avoid_text.strip()}」被指出不对，同类话题别再这么说；拿不准就不说。"
        elif isinstance(correction_text, str) and correction_text.strip():
            text = f"在本会话被这样纠正过：「{correction_text.strip()}」，同类话题别再犯同样的错；拿不准就不说。"
        else:
            continue
        experiences.append({"kind": "correction", "text": text})
    return experiences[-limit:] if limit > 0 else []
