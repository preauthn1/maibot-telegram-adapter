"""中文群聊拟人化处理。

与 blader/humanizer 的关系：借鉴其"按具体模式清单逐条命名 + 保留原意"的方法论，
但**规则集完全重写**。原项目面向英文百科/长文散文（em dash、title case、
"delve/tapestry" 等），对中文即时通讯毫无意义。

本模块针对的是**中文群聊里 AI 的破绽**，来自真实聊天记录观察：

- 书面语连接词（此外、然而、总的来说、值得一提的是）
- 助手腔与过度礼貌（好的、没问题、希望能帮到你）
- 强行三连排比
- 每句都带句号（真人打字很少用句号收尾）
- emoji 当装饰品
- 总结式结尾（总而言之、希望对你有帮助）
- 单条消息过长
- 逐条回应对方每一个点（真人只挑一个点接话）
- 中文破折号、书名号等书面标点

所有处理都是**保守的**：只删不编，绝不新增事实。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Pattern, Tuple

import random
import re

# --------------------------------------------------------------------------
# 1. 书面语连接词 —— 群聊里几乎没人这么说话
# --------------------------------------------------------------------------
_FORMAL_CONNECTIVES: Tuple[Tuple[str, str], ...] = (
    (r"^\s*此外[，,]?\s*", ""),
    (r"^\s*另外[，,]\s*", ""),
    (r"^\s*然而[，,]?\s*", ""),
    (r"^\s*不过话说回来[，,]?\s*", ""),
    (r"^\s*总的来说[，,]?\s*", ""),
    (r"^\s*总而言之[，,]?\s*", ""),
    (r"^\s*综上所述[，,]?\s*", ""),
    (r"^\s*一方面[，,]?\s*", ""),
    (r"^\s*另一方面[，,]?\s*", ""),
    (r"^\s*值得(?:一提|注意)的是[，,]?\s*", ""),
    (r"^\s*需要(?:注意|指出)的是[，,]?\s*", ""),
    (r"^\s*事实上[，,]\s*", ""),
    (r"^\s*客观(?:来说|而言)[，,]?\s*", ""),
    (r"^\s*从(?:某种|这个)(?:意义|角度)(?:上)?(?:来)?(?:说|讲)[，,]?\s*", ""),
    (r"^\s*首先[，,]\s*", ""),
    (r"^\s*其次[，,]\s*", ""),
    (r"^\s*最后[，,]\s*", ""),
    (r"因此[，,]?", "所以"),
    (r"[，,]?从而", "，"),
    (r"[，,]?并且", "，"),
    (r"以及", "和"),
    (r"或者说", "或者"),
    (r"是否", "是不是"),
    (r"能够", "能"),
    (r"进行(?=[一-鿿]{2,4})", ""),
)

# --------------------------------------------------------------------------
# 2. 助手腔 / 客服腔 —— 最刺眼的破绽
# --------------------------------------------------------------------------
_ASSISTANT_TONE: Tuple[str, ...] = (
    r"希望(?:这|以上|对你|能)(?:些)?(?:内容|信息|回答|建议)?(?:对你|对您)?(?:有(?:所)?帮助|有用)[。.！!]?",
    r"希望能帮(?:到|助)(?:你|您)[。.！!]?",
    r"如果(?:你|您)(?:还有|有)(?:其他|任何|别的)(?:问题|疑问|需要)[，,]?(?:可以|欢迎|随时)?(?:随时)?(?:问我|告诉我|联系我)[。.！!]?",
    # 注意：必须精确锚定"完整的客服套话"，不能泛匹配"有什么…"。
    # 群聊里"你有什么想法""有什么好吃的"都是正常问句，误删会毁掉句子。
    r"(?:还)?有(?:什么|啥)(?:其他|别的)?(?:我)?(?:可以|能)(?:帮(?:助)?(?:你|您)|为(?:你|您)(?:效劳|服务))(?:的)?(?:地方|问题)?(?:吗|嘛|么)?[？?！!。.]?",
    r"(?:还)?有(?:什么|啥)(?:其他|别的)(?:问题|需要|疑问)(?:吗|嘛|么)?[？?！!。.]?",
    r"需要我(?:帮(?:你|您))?(?:做)?(?:什么|点什么|些什么)(?:吗|嘛|么)?[？?！!。.]?",
    r"很高兴(?:能)?(?:帮(?:到|助)|为)(?:你|您)(?:服务)?[。.！!]?",
    r"^\s*好的[，,！!。.]\s*",
    r"^\s*没问题[，,！!。.]\s*",
    r"^\s*当然(?:可以)?[，,！!。.]\s*",
    r"^\s*收到[，,！!。.]\s*",
    r"^\s*明白了?[，,！!。.]\s*",
    r"^\s*(?:这是|以下是|下面是)(?:一(?:些|个))?.{0,10}[：:]\s*",
    r"^\s*让我(?:来)?(?:帮(?:你|您)|为(?:你|您))?(?:分析|看看|解释|说明)(?:一下)?[，,：:。.]?\s*",
    r"^\s*(?:好|嗯)问题[！!。.]?\s*",
    r"(?:你|您)(?:说得|说的)(?:很|非常|太)?(?:对|有道理)[，,。.！!]?",
    r"^\s*我(?:理解|明白)(?:你|您)(?:的)?(?:意思|感受|心情)[，,。.]?\s*",
    r"^\s*总(?:的来说|而言之|之)[，,]?\s*",
    r"请(?:注意|放心|相信)[，,]?",
    r"[，,]?供(?:你|您)参考[。.]?",
)

# --------------------------------------------------------------------------
# 3. 书面标点 —— 群聊里不会出现
# --------------------------------------------------------------------------
_PUNCTUATION_FIXES: Tuple[Tuple[str, str], ...] = (
    (r"——+", "，"),      # 中文破折号
    (r"—+", "，"),        # em dash
    (r"–+", "，"),        # en dash
    (r"《([^》]{1,20})》", r"\1"),   # 书名号
    (r"、", "，"),         # 顿号在聊天里少见
    (r"；", "，"),         # 分号
    (r"…{1,}", "。。。"),  # 省略号改成口语化的句点
    (r"\.{3,}", "。。。"),
    (r"“([^”]*)”", r"\1"),  # 弯引号
    (r"‘([^’]*)’", r"\1"),
    (r"【([^】]*)】", r"\1"),
)

# --------------------------------------------------------------------------
# 4. 装饰性 emoji —— 保留少量，删掉堆砌
# --------------------------------------------------------------------------
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001f300-\U0001f9ff"
    "\U0001fa00-\U0001faff"
    "\u2600-\u27bf"
    "\U0001f000-\U0001f2ff"
    "]+",
    flags=re.UNICODE,
)

# 行首装饰 emoji（"🚀 今天…"）在群聊里是明显的 AI 味
_LEADING_EMOJI = re.compile(r"^\s*" + _EMOJI_PATTERN.pattern + r"\s*")

# --------------------------------------------------------------------------
# 5. Markdown 残留 —— 群聊不渲染 markdown
# --------------------------------------------------------------------------
_MARKDOWN_FIXES: Tuple[Tuple[str, str], ...] = (
    (r"\*\*([^*]+)\*\*", r"\1"),
    (r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1"),
    (r"^#{1,6}\s*", ""),
    (r"^\s*[-*+]\s+", ""),
    (r"^\s*\d+[.、]\s+", ""),
    (r"`([^`]+)`", r"\1"),
)

_COMPILED_FORMAL = tuple((re.compile(p), r) for p, r in _FORMAL_CONNECTIVES)
_COMPILED_ASSISTANT: Tuple[Pattern[str], ...] = tuple(re.compile(p) for p in _ASSISTANT_TONE)
_COMPILED_PUNCT = tuple((re.compile(p), r) for p, r in _PUNCTUATION_FIXES)
_COMPILED_MARKDOWN = tuple((re.compile(p, re.MULTILINE), r) for p, r in _MARKDOWN_FIXES)


@dataclass
class HumanizeResult:
    """拟人化处理结果。"""

    text: str
    """处理后的文本；整条都是助手腔时为空串。"""

    changed: bool = False
    """是否发生任何修改。"""

    applied_rules: List[str] = field(default_factory=list)
    """命中的规则名，用于调试日志。"""

    became_empty: bool = False
    """整条消息都是无信息量的助手腔，被完全删空。

    此时调用方应当**跳过发送**：真人不会为了说话而说话，沉默比发一句
    "有什么可以帮你的吗"更像人。
    """


def _strip_trailing_period(text: str) -> str:
    """去掉句尾句号。

    真人在群聊里几乎不用句号收尾，但问号和感叹号会保留。

    Args:
        text: 原始文本。

    Returns:
        str: 处理后的文本。
    """

    return re.sub(r"[。.]+\s*$", "", text)


def _collapse_emoji(text: str, max_emoji: int) -> Tuple[str, bool]:
    """限制 emoji 数量并删除行首装饰 emoji。

    Args:
        text: 原始文本。
        max_emoji: 允许保留的 emoji 上限。

    Returns:
        Tuple[str, bool]: ``(处理后文本, 是否修改)``。
    """

    changed = False

    stripped = _LEADING_EMOJI.sub("", text)
    if stripped != text:
        changed = True
        text = stripped

    matches = list(_EMOJI_PATTERN.finditer(text))
    if len(matches) > max_emoji:
        # 从后往前删，保留最靠前的 max_emoji 个。
        for match in reversed(matches[max_emoji:]):
            text = text[: match.start()] + text[match.end() :]
        changed = True

    return text, changed


def _tidy(text: str) -> str:
    """收敛删除后留下的多余标点与空白。

    Args:
        text: 待清理文本。

    Returns:
        str: 清理后的文本。
    """

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"^[，,。.、；;：:\s]+", "", text)
    text = re.sub(r"[，,]+([。.！!？?])", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def humanize_chat_text(
    text: str,
    *,
    drop_trailing_period: bool = True,
    max_emoji: int = 1,
    strip_markdown: bool = True,
) -> HumanizeResult:
    """把一条 LLM 回复改写成更像真人打字的中文群聊文本。

    只做删减与替换，不新增任何内容。

    Args:
        text: LLM 原始回复。
        drop_trailing_period: 是否去掉句尾句号。
        max_emoji: 允许保留的 emoji 数量。
        strip_markdown: 是否剥离 markdown 标记。

    Returns:
        HumanizeResult: 处理结果。若 ``became_empty`` 为真，说明整条都是助手腔，
        调用方应跳过发送而不是退回原文。
    """

    original = text or ""
    if not original.strip():
        return HumanizeResult(text=original)

    current = original
    applied: List[str] = []

    if strip_markdown:
        for pattern, replacement in _COMPILED_MARKDOWN:
            new_text, count = pattern.subn(replacement, current)
            if count:
                current = new_text
                applied.append("markdown")

    for pattern in _COMPILED_ASSISTANT:
        new_text, count = pattern.subn("", current)
        if count:
            current = new_text
            applied.append("assistant_tone")

    for pattern, replacement in _COMPILED_FORMAL:
        new_text, count = pattern.subn(replacement, current)
        if count:
            current = new_text
            applied.append("formal_connective")

    for pattern, replacement in _COMPILED_PUNCT:
        new_text, count = pattern.subn(replacement, current)
        if count:
            current = new_text
            applied.append("punctuation")

    current, emoji_changed = _collapse_emoji(current, max_emoji)
    if emoji_changed:
        applied.append("emoji")

    current = _tidy(current)

    if drop_trailing_period:
        stripped = _strip_trailing_period(current)
        if stripped != current:
            current = stripped
            applied.append("trailing_period")

    # 整条都被删空，说明这句话除了助手腔没有任何信息量。
    # 此时应当跳过发送，而不是退回原文把最糟糕的 AI 味原样发出去。
    if not current.strip():
        return HumanizeResult(
            text="",
            changed=True,
            applied_rules=sorted(set(applied)),
            became_empty=True,
        )

    return HumanizeResult(
        text=current,
        changed=current != original,
        applied_rules=sorted(set(applied)),
    )


def should_reply_briefly(incoming_text: str, threshold: int = 12) -> bool:
    """判断是否应该用短回复。

    真人在群里对短消息几乎都用短回复，对长消息才可能多说几句。

    Args:
        incoming_text: 对方消息文本。
        threshold: 判定为"短消息"的字数阈值。

    Returns:
        bool: 建议短回复时返回 ``True``。
    """

    return len((incoming_text or "").strip()) <= threshold


def pick_typo_free_probability(base: float, text_length: int) -> float:
    """按文本长度调节错别字概率。

    真人打长文时更容易出错，但也更可能回头检查，因此概率增长是次线性的。

    Args:
        base: 基础错别字概率。
        text_length: 文本长度。

    Returns:
        float: 调节后的概率，限制在 [0, 0.5]。
    """

    if text_length <= 0:
        return 0.0
    scaled = base * (1.0 + min(text_length, 100) / 200.0)
    return max(0.0, min(scaled, 0.5))


def jitter(value: float, ratio: float = 0.25) -> float:
    """给一个时长加上随机抖动。

    固定节奏是自动化最容易被识破的特征。

    Args:
        value: 原始秒数。
        ratio: 抖动比例。

    Returns:
        float: 抖动后的秒数，不小于 0。
    """

    if value <= 0:
        return 0.0
    low = max(0.0, 1.0 - ratio)
    high = 1.0 + ratio
    return max(0.0, value * random.uniform(low, high))
