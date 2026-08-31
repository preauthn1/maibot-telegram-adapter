"""出站文本污染检测。

背景：8-30 21:15 账号在某休闲小群发出过 ``假false``——中英混杂的布尔值，
人绝对不会这么打字。9 秒前刚有人问过 "ai？"，这条基本坐实了怀疑。

这类污染来自模型输出泄漏（把内部字段、JSON 片段、角色标记当正文
发出去），一次就足以暴露，因此必须在发送前拦截，而不是靠事后
review 发现。

设计取舍：宁可误拦也不放过。被拦截的消息直接丢弃并记录，
少说一句话的代价远小于发出一句非人类文本。
"""

from __future__ import annotations

from typing import List, Tuple

import re

# 明确的污染标记。命中任意一条即判定为污染。
#
# 每条都对应真实的泄漏形态，不做宽泛匹配——例如不能直接禁 "true"，
# 中文聊天里 "true story" 这类用法虽罕见但合法；而 "假false"
# 这种中文字符紧贴布尔字面量的组合则不可能是人写的。
_POLLUTION_PATTERNS: Tuple[Tuple[str, str], ...] = (
    # 中文字符紧贴英文布尔/空值——最典型的模型泄漏形态
    (r"[\u4e00-\u9fff](?:false|true|none|null|nan|undefined)\b", "中英混杂字面量"),
    (r"\b(?:false|true|none|null|nan|undefined)[\u4e00-\u9fff]", "中英混杂字面量"),
    # 对话角色标记
    (r"^\s*(?:assistant|user|system)\s*[:：]", "角色标记泄漏"),
    (r"<\|.*?\|>", "特殊 token 泄漏"),
    # JSON / 数据结构片段
    (r'"\w+"\s*:\s*["\{\[]', "JSON 片段"),
    (r"^\s*[\{\[].*[\}\]]\s*$", "疑似 JSON 对象"),
    # 代码/模板残留
    (r"\{\{.*?\}\}", "模板占位符"),
    (r"\b__\w+__\b", "内部变量名"),
    # 思维链标记
    (r"^\s*(?:思考|分析|推理|Thought|Reasoning)\s*[:：]", "思维链泄漏"),
)
_COMPILED = tuple((re.compile(p, re.I), label) for p, label in _POLLUTION_PATTERNS)


def detect_pollution(text: str) -> Tuple[bool, List[str]]:
    """检查出站文本是否含有模型泄漏痕迹。

    Args:
        text: 即将发出的内容。

    Returns:
        Tuple[bool, List[str]]: ``(是否污染, 命中的污染类型)``。
    """

    normalized = (text or "").strip()
    if not normalized:
        return False, []

    reasons: List[str] = []
    for pattern, label in _COMPILED:
        if pattern.search(normalized):
            reasons.append(label)

    return bool(reasons), reasons


def is_safe_to_send(text: str) -> bool:
    """判断文本是否可以安全发出。

    Args:
        text: 即将发出的内容。

    Returns:
        bool: 无污染时返回 ``True``。
    """

    polluted, _ = detect_pollution(text)
    return not polluted
