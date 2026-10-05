"""从当前会话的工具历史收集本轮记忆参考，不放开全部工具结果。"""
from collections.abc import Sequence
from .messages import LLMContextMessage, ToolResultMessage


def collect_reply_memory_references(history: Sequence[LLMContextMessage], logical_turn_id: str) -> list[str]:
    """调用方必须传入当前会话历史及引擎实际轮次；不猜测最新轮次。"""
    if not isinstance(logical_turn_id, str) or not logical_turn_id.strip():
        return []
    references: list[str] = []
    seen: set[str] = set()
    for message in history:
        if not isinstance(message, ToolResultMessage):
            continue
        if message.logical_turn_id != logical_turn_id or message.tool_name != 'query_memory' or message.success is not True:
            continue
        reference = message.metadata.get('replyer_memory_reference')
        if not isinstance(reference, str) or not reference.strip() or reference in seen:
            continue
        # 不strip正文：格式化结果中的缩进与尾换行必须保留。
        references.append(reference)
        seen.add(reference)
    return references
