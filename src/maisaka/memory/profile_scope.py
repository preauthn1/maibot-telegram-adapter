"""人物画像出口共用的会话证据校验；未知或不完整证据拒绝输出。"""

from typing import Any, Dict, Tuple


def check_profile_scope(payload: Dict[str, Any], session_id: str) -> Tuple[bool, str]:
    """只允许证据全部属于当前真实会话的完整快照，不跨私聊或群共享。"""
    if not session_id:
        return False, "missing_session"
    if payload.get("success") is not True:
        return False, "invalid_receipt"
    if payload.get("has_manual_override") or payload.get("manual_override_text"):
        return False, "unscoped_manual_override"
    evidence = payload.get("evidence")
    total = payload.get("evidence_count")
    if not isinstance(evidence, list) or not evidence:
        return False, "missing_evidence"
    if type(total) is not int or total != len(evidence):
        return False, "incomplete_evidence"
    for item in evidence:
        if not isinstance(item, dict):
            return False, "invalid_evidence"
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            return False, "unknown_scope"
        scopes = set()
        for key in ("chat_id", "session_id"):
            value = metadata.get(key)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    return False, "invalid_scope"
                scopes.add(value.strip())
        values = metadata.get("chat_ids", [])
        if not isinstance(values, list):
            return False, "invalid_scope_list"
        for value in values:
            if not isinstance(value, str) or not value.strip():
                return False, "invalid_scope"
            scopes.add(value.strip())
        if scopes != {session_id}:
            return False, "foreign_or_unknown_scope"
    return True, "current_session_only"
