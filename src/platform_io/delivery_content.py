"""纯函数：校验版本化发送正文回执，不把内容错误转换为投递失败。"""

from typing import Any, Dict, List, Optional, Tuple

CONTENT_KEY = "delivery_content"
HISTORY_BLOCK_KEY = "_delivery_content_history_blocked"


def validate_text_content(value: Any, external_id: Optional[str]) -> Optional[List[str]]:
    """只接受完整列举全部成功发送的纯文本正文（不是全部候选发送成功）。"""
    if not isinstance(value, dict):
        return None
    if type(value.get("version")) is not int or value["version"] != 1:
        return None
    if value.get("scope") != "text_only" or value.get("complete") is not True:
        return None
    parts = value.get("parts")
    if not isinstance(parts, list) or not parts:
        return None
    ids = set()
    texts = []
    for part in parts:
        if not isinstance(part, dict):
            return None
        mid, text = part.get("message_id"), part.get("text")
        if not isinstance(mid, str) or not mid.strip() or mid in ids:
            return None
        if not isinstance(text, str) or not text:
            return None
        source = part.get("source")
        if not isinstance(source, str) or source not in {"telegram_message", "unparsed_transport"}:
            return None
        ids.add(mid)
        texts.append(text)
    if parts[-1]["message_id"] != external_id:
        return None
    return texts


def select_text_content(receipts: List[Dict[str, Any]], *, text_only: bool) -> Tuple[str, Optional[List[str]]]:
    """旧驱动和媒体/多路发送不改写；声明了契约但损坏的正文禁止写历史。"""
    if not text_only or len(receipts) != 1:
        return "unsupported", None
    metadata = receipts[0]["metadata"]
    if not isinstance(metadata, dict) or CONTENT_KEY not in metadata:
        return "legacy", None
    texts = validate_text_content(metadata[CONTENT_KEY], receipts[0]["external_message_id"])
    return ("confirmed", texts) if texts is not None else ("invalid", None)
