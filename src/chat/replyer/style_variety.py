"""回复风格多样性提示（防止语言风格固化）。

根据自身最近的实际出站动态指出高频重复的表达习惯（如句尾句号、逗号两段式、
高频客服铺垫词、句首重复词等），并按真人句长分布随机给出本条的长度档位。

本模块只产出提示词文本，不改写模型输出，不参与任何频率闸门。
"""

from collections import Counter
from typing import Iterable, List, Optional, Sequence

import random
import re

# 只看最近这么多条自己的发言；太长会把很久以前的习惯也算进来。
RECENT_WINDOW = 12
# 最少样本数：样本太少时统计没有意义，不给提示。
MIN_SAMPLES = 4

_EMOJI = re.compile("[\U0001f300-\U0001f9ff\U0001fa00-\U0001faff\u2600-\u27bf]")

# 长度档位按群聊真人分布取权重：≤4 字约 22%，5~12 字约 43%，其余为正常一句。
ULTRA_SHORT_MODE = "这次只回两三个字或一个短词就够了，只针对目标消息表态，不要补充，也不要只吐无指代的「对/对喽」。"
LENGTH_MODES: Sequence[tuple[str, float]] = (
    (ULTRA_SHORT_MODE, 0.22),
    ("这次很短，半句话，不用把意思说全。", 0.43),
    ("这次正常说一句，长短看内容。", 0.35),
)

# 目标消息是在提问、或涉及身份/测试/实现追问时，不能抽到极短档。
_QUESTION = re.compile(
    r"[？?]|吗|么|呢|怎么|咋|啥|什么|哪|为什么|如何|是不是|能不能|可不可以|有没有|行不行|好了没"
    r"|bot|机器人|人机|模型|接管|mcp|openclaw|提示词|prompt|9\.8|9\.11|\d+\s*[+\-*/]\s*\d+",
    re.IGNORECASE,
)

# 统计「开头」时只看前两个字；标点开头的不算。
_OPENER_LEN = 2


def _openers(texts: Iterable[str]) -> Counter:
    counter: Counter = Counter()
    for text in texts:
        head = text.strip()[:_OPENER_LEN]
        if len(head) == _OPENER_LEN and not re.match(r"[\W_]", head[0]):
            counter[head] += 1
    return counter


def is_question(text: str) -> bool:
    """粗判目标消息是否在向人提问。"""

    return bool(_QUESTION.search(text or ""))


def pick_length_mode(rng: Optional[random.Random] = None, *, target_is_question: bool = False) -> str:
    """按真人长度分布随机选择本条回复的长度档位；回答提问时排除「只回一两个字」。"""

    modes = [(t, w) for t, w in LENGTH_MODES if not (target_is_question and t == ULTRA_SHORT_MODE)]
    total = sum(w for _, w in modes)
    roll = (rng.random() if rng is not None else random.random()) * total
    cumulative = 0.0
    for text, weight in modes:
        cumulative += weight
        if roll < cumulative:
            return text
    return modes[-1][0]


def overused_patterns(own_texts: Sequence[str]) -> List[str]:
    """从自己最近的发言里找出已经用多了的表达习惯。

    Args:
        own_texts: 自己最近发出的文本，按时间顺序。

    Returns:
        List[str]: 每项是一条可直接放进提示词的中文描述；没有问题时为空列表。
    """

    recent = [t.strip() for t in own_texts if t and t.strip()][-RECENT_WINDOW:]
    if len(recent) < MIN_SAMPLES:
        return []
    n = len(recent)
    notes: List[str] = []

    with_emoji = sum(1 for t in recent if _EMOJI.search(t))
    if with_emoji / n >= 0.25:
        used = Counter(m.group(0) for t in recent for m in _EMOJI.finditer(t))
        top = "".join(e for e, _ in used.most_common(3))
        notes.append(f"你最近 {n} 条里有 {with_emoji} 条带了 emoji（{top}），这次不要带 emoji")

    comma_two = sum(1 for t in recent if "，" in t or "," in t)
    if comma_two / n >= 0.25:
        notes.append("你最近总是「前半句，后半句」的两段式（同群真人 82% 不打逗号），这次别用逗号分两段，直接一句话说完")

    trailing_period = sum(
        1
        for t in recent
        if re.sub(r"[\U0001f300-\U0001f9ff\U0001fa00-\U0001faff\u2600-\u27bf\s]+$", "", t).endswith("。")
    )
    if trailing_period / n >= 0.25:
        notes.append(f"你最近 {n} 条里有 {trailing_period} 条句尾带了句号「。」，这次句尾不要加句号")

    for word, limit in (("先", 2), ("试试", 2), ("目前", 2), ("可以", 3)):
        w_count = sum(1 for t in recent if word in t)
        if w_count >= limit:
            notes.append(f"你最近 {n} 条里有 {w_count} 条用了「{word}」（远超真人频率），这次不要用「{word}」")

    for head, count in _openers(recent).most_common(2):
        if count >= 3:
            notes.append(f"你最近多次用「{head}」开头，这次换个开头")

    short_exact = [t for t in recent if len(t) <= 12]
    if short_exact:
        joined = " / ".join(dict.fromkeys(short_exact[-6:]))
        notes.append(f"你最近已经发过这些短句（{joined}），这次绝不要原样复读或只改标点")

    lengths = sorted(len(t) for t in recent)
    if lengths[0] > 4 and lengths[-1] - lengths[0] <= 12:
        notes.append("你最近每条长度都差不多，这次长短要和前面明显不同")

    return notes


# 口头禅：真人用得很少、模型却极爱用的固定附和词，以及曾造成复读/顺话认领的模板短句。
VERBAL_TICS: Sequence[str] = ("确实", "的确", "那就", "就行", "对喽", "啊？我人啊", "我人啊", "打磨")
TIC_WINDOW = 40


def banned_tics(own_texts: Sequence[str]) -> List[str]:
    """返回本条回复禁止使用的口头禅（最近 ``TIC_WINDOW`` 条自己的发言里已出现过的）。"""

    recent = [t for t in own_texts if t][-TIC_WINDOW:]
    return [tic for tic in VERBAL_TICS if any(tic in t for t in recent)]


def tic_violation(text: str, banned: Sequence[str]) -> Optional[str]:
    """生成结果用了本条禁用的口头禅时，返回命中的词。"""

    for tic in banned:
        if tic in (text or ""):
            return tic
    return None


def style_variety_prompt_line(
    own_texts: Sequence[str],
    *,
    banned: Optional[Sequence[str]] = None,
    rng: Optional[random.Random] = None,
    target_is_question: bool = False,
) -> str:
    """生成注入 replyer 额外要求的一段话。"""

    parts: List[str] = [pick_length_mode(rng, target_is_question=target_is_question)]
    if target_is_question:
        parts.append("对方在问问题，要正面答到点上，不要只回一个「？」或语气词。")
    notes = overused_patterns(own_texts)
    if notes:
        parts.append("；".join(notes) + "。")
    active_banned = list(banned) if banned is not None else banned_tics(own_texts)
    if active_banned:
        quoted = "、".join(f"「{t}」" for t in active_banned)
        parts.append(f"这次不许出现{quoted}，换别的说法或者直接说内容。")
    parts.append("不用每句都表达情绪，大多数时候平平地说。")
    return "".join(parts)
