"""纯函数：校验版本化发送正文回执，不把内容错误转换为投递失败。"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.common.data_models.message_component_data_model import MessageSequence, ReplyComponent

CONTENT_KEY = "delivery_content"
PARTIAL_KEY = "delivery_partial"
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


def validate_segment_content(value: Any, component_count: int) -> Optional[Tuple[List[int], bool]]:
    """校验混合/媒体批次回执：只接受落在原始组件范围内、不重复的已确认下标。"""
    if not isinstance(value, dict):
        return None
    if type(value.get("version")) is not int or value["version"] != 1:
        return None
    if value.get("scope") != "segments" or type(value.get("complete")) is not bool:
        return None
    indices = value.get("confirmed_indices")
    # 成功回执至少确认一个组件；空列表不能当作成功送达的内容。
    if not isinstance(indices, list) or not indices:
        return None
    if any(type(index) is not int or not 0 <= index < component_count for index in indices):
        return None
    if len(set(indices)) != len(indices):
        return None
    return sorted(indices), value["complete"]


def select_segment_content(
    receipts: List[Dict[str, Any]], *, component_count: int
) -> Tuple[str, Optional[Tuple[List[int], bool]]]:
    """非纯文本批次：旧驱动/多路发送不改写；文本契约交给 select_text_content 的语义（不改写）。"""
    if len(receipts) != 1:
        return "unsupported", None
    metadata = receipts[0]["metadata"]
    if not isinstance(metadata, dict) or CONTENT_KEY not in metadata:
        return "legacy", None
    value = metadata[CONTENT_KEY]
    # 适配器按段类型判定为纯文本（如 telegram_buttons）而宿主视为非纯文本时，保持旧行为。
    if isinstance(value, dict) and value.get("scope") == "text_only":
        return "unsupported", None
    result = validate_segment_content(value, component_count)
    return ("confirmed", result) if result is not None else ("invalid", None)


def materialize_confirmed_segments(sequence: MessageSequence, confirmed_indices: Sequence[int]) -> MessageSequence:
    """只保留已确认送达的组件；Reply 组件是不单独投递的引用元数据，始终保留。"""
    confirmed = set(confirmed_indices)
    return MessageSequence(components=[
        component for index, component in enumerate(sequence.components)
        if index in confirmed or isinstance(component, ReplyComponent)
    ])
