"""出站噪音过滤。

主程序的中文错别字功能（``src/chat/utils/utils.py``）在打错字后会追加
一条"纠正消息"，内容仅是单个正确字。真人不会孤零零发一个"什"，
这类消息比错别字本身更容易暴露身份，因此在出站层拦掉。

判定只针对"单个汉字"，不能误杀真人常用的短回复：
"哈哈""确实""好""6""?" 都必须放行。
"""

from __future__ import annotations

# 允许单字出现的白名单：真人确实会单独发这些。
_ALLOWED_SINGLE_CHARS = frozenset(
    {
        "好",
        "对",
        "行",
        "是",
        "在",
        "来",
        "去",
        "有",
        "没",
        "会",
        "能",
        "要",
        "想",
        "草",
        "顶",
        "赞",
        "牛",
        "强",
        "秒",
        "懂",
        "服",
        "绝",
        "笑",
        "哭",
        "晕",
        "困",
        "饿",
        "冷",
        "热",
        "累",
    }
)


def _is_chinese_char(value: str) -> bool:
    """判断是否为单个中日韩统一表意文字。"""

    return "\u4e00" <= value <= "\u9fff"


def is_noise_text(text: str) -> bool:
    """判断一段出站文本是否为应当丢弃的噪音。

    Args:
        text: 待发送的文本。

    Returns:
        bool: 为 True 时不应发送。
    """

    stripped = text.strip()
    if not stripped:
        return True

    # 仅拦截"单个汉字"这一种形态：错别字纠正消息就长这样。
    # 数字、英文字母、标点、emoji 等单字符是真人常用回复，一律放行。
    if len(stripped) == 1 and _is_chinese_char(stripped):
        return stripped not in _ALLOWED_SINGLE_CHARS

    return False
