"""只识别结构化目标原文中的狭窄短确认契约；不读取状态或执行 IO。"""
from typing import Any, Optional
import re


_WORDS = ('好', '好的', '收到', '行', '可以', '明白', '明白了')
# 完整句式匹配，不从引用、否定、条件句或其他额外要求中搜索指令。
_REQUEST = re.compile(
    r'(?:请确认方案[A-Za-z0-9一二三四五六七八九十甲乙丙丁]+[，,])?'
    r'(?:请)?只回复(?:“(?P<cn>好|好的|收到|行|可以|明白|明白了)”'
    r'|‘(?P<single>好|好的|收到|行|可以|明白|明白了)’'
    r'|"(?P<ascii>好|好的|收到|行|可以|明白|明白了)"'
    r'|(?P<plain>好|好的|收到|行|可以|明白|明白了))[。.!！]?'
)


def positive_message_id(value: Any) -> Optional[int]:
    """不接受 bool、浮点、带符号或任意对象的强制转换。"""
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,20}', value):
        number = int(value)
        return number if number > 0 else None
    return None


def acknowledgement_word(raw_message: Any, explicit_target_message_id: Any,
                         configured_target: Any = None) -> Optional[str]:
    """整个 payload 只能有一个 reply 和一个精确白名单 text 段。"""
    target = positive_message_id(explicit_target_message_id)
    if target is None or not isinstance(raw_message, list) or len(raw_message) != 2:
        return None
    if configured_target is not None and positive_message_id(configured_target) != target:
        return None
    if any(not isinstance(seg, dict) for seg in raw_message):
        return None
    replies = [seg for seg in raw_message if seg.get('type') == 'reply']
    texts = [seg for seg in raw_message if seg.get('type') == 'text']
    if len(replies) != 1 or len(texts) != 1:
        return None
    data = replies[0].get('data')
    if not isinstance(data, dict) or positive_message_id(data.get('target_message_id')) != target:
        return None
    sender = data.get('target_message_sender_id')
    if not isinstance(sender, str) or not sender.strip():
        return None
    source = data.get('target_message_content')
    word = texts[0].get('data')
    if not isinstance(source, str) or not isinstance(word, str) or word not in _WORDS:
        return None
    match = _REQUEST.fullmatch(source.strip())
    if match is None or word not in match.groups():
        return None
    return word
