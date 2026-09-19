"""语言风格指标：把“像不像同一套机器人模板”变成可回归的数字。"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import log2
from typing import Mapping, Sequence
from .style_profiles import is_adapter_envelope


@dataclass(frozen=True)
class StyleMetrics:
    """本地 transcript 的风格指标快照。"""

    sample_count: int
    cross_chat_reuse_rate: float
    length_entropy: float
    top_opening_words: list[tuple[str, int]]


def _opening_word(text: str) -> str:
    """取前四个可见字符，适配没有空格分词的中文聊天。"""

    return "".join(str(text).split())[:4]


def _length_bucket(text: str) -> str:
    length = len("".join(str(text).split()))
    if length <= 2:
        return "1-2"
    if length <= 6:
        return "3-6"
    if length <= 12:
        return "7-12"
    if length <= 30:
        return "13-30"
    return "31+"


def _entropy(counter: Counter[str], total: int) -> float:
    if total <= 0:
        return 0.0
    return -sum((count / total) * log2(count / total) for count in counter.values())


def compute_style_metrics(messages_by_chat: Mapping[str, Sequence[str]]) -> StyleMetrics:
    """计算跨聊天流短句复用、长度熵与高频开头。

    输入应只包含账号自己实际发送的文本。没有样本时返回零值，不产生
    虚假的“风格良好”结论。
    """

    rows = [
        (str(chat_id), "".join(str(text).split()))
        for chat_id, messages in messages_by_chat.items()
        for text in messages
        if "".join(str(text).split())
        and not is_adapter_envelope("".join(str(text).split()))
    ]
    total = len(rows)
    if total == 0:
        return StyleMetrics(0, 0.0, 0.0, [])

    chats_by_text: dict[str, set[str]] = defaultdict(set)
    for chat_id, text in rows:
        chats_by_text[text].add(chat_id)
    reused = sum(1 for _, text in rows if len(chats_by_text[text]) > 1)
    length_counts = Counter(_length_bucket(text) for _, text in rows)
    opening_counts = Counter(_opening_word(text) for _, text in rows)
    return StyleMetrics(
        sample_count=total,
        cross_chat_reuse_rate=reused / total,
        length_entropy=_entropy(length_counts, total),
        top_opening_words=opening_counts.most_common(10),
    )
