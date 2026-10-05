"""回复信息密度对齐（让我们的一句话和群友一句话装的信息差不多）。

问题：单纯压字数上限，模型会把原本两三句的内容挤进一句，信息密度反而远高于人。
正确做法是**减少要说的点**，而不是压缩表达。

做法：
1. 目标长度来自当前聊天流最近**群友**发言**正文**的中位数（动态、按会话），
   不含麦麦自己，不含说话人前缀/引用块。链接、代码、长转发这类不是"随口一句话"，
   不进基线，否则会被少数长消息拉高。
2. 提示词里给出这个具体数字，并明确"只说一个点；想说的多就挑一个，其余不说"。
3. 生成后若超过超长线（群友 P75 与 2×中位数取小），或一句里塞了多个信息点，
   触发重生成，约束是"删掉要点"而不是"缩写"。
"""

from statistics import median
from typing import Iterable, List, Optional, Tuple

import re

DEFAULT_TARGET = 14
MIN_TARGET = 6
MAX_TARGET = 24
MIN_SAMPLES = 5
# 超过这个长度的群友消息多半是转发/长文，不是"一句话"，不进基线。
CHAT_MESSAGE_MAX_LEN = 80
_CLAUSE_SPLIT = re.compile(r"[，,；;。！!？?…]+|\s{2,}")
_LIST_MARK = re.compile(r"(?:^|\s)(?:\d+[.、)]|[-•·])\s*|首先|其次|另外|而且还|此外|总之")
_NON_CHAT = re.compile(r"https?://|t\.me/|```|\n.*\n")


def _chat_lengths(peer_texts: Iterable[str]) -> List[int]:
    """群友"随口一句话"的长度列表：去掉链接、代码、多行长文。"""

    lengths: List[int] = []
    for text in peer_texts:
        stripped = (text or "").strip()
        if not stripped or _NON_CHAT.search(stripped):
            continue
        if len(stripped) > CHAT_MESSAGE_MAX_LEN:
            continue
        lengths.append(len(stripped))
    return lengths


def target_length(peer_texts: Iterable[str]) -> int:
    """当前聊天群友最近发言正文的中位长度，裁剪到 [6, 24]（用于提示词）。"""

    lengths = _chat_lengths(peer_texts)
    if len(lengths) < MIN_SAMPLES:
        return DEFAULT_TARGET
    return int(max(MIN_TARGET, min(MAX_TARGET, round(median(lengths)))))


def length_ceiling(peer_texts: Iterable[str]) -> int:
    """超长判定线：群友 P75 与 2×中位数取小。

    技术群长短两极分化（P75 常是中位数的 2.5 倍），只用 P75 会放过明显偏长的回复，
    所以再用 2×中位数兜住"比普通一句话长一倍"的情况。
    """

    lengths = sorted(_chat_lengths(peer_texts))
    if len(lengths) < MIN_SAMPLES:
        return DEFAULT_TARGET * 2
    index = min(len(lengths) - 1, int(len(lengths) * 0.75))
    return max(12, min(40, lengths[index], 2 * round(median(lengths))))


def count_points(text: str) -> int:
    """粗估一条回复里的信息点数：分句数 + 列举标记。语气词短分句不计。"""

    clauses = [c for c in _CLAUSE_SPLIT.split(text or "") if len(c.strip()) >= 4]
    return len(clauses) + len(_LIST_MARK.findall(text or ""))


def density_violation(text: str, target: int, ceiling: int) -> Optional[Tuple[str, str]]:
    """返回 (原因, 重生成约束)；未违规返回 None。

    Args:
        text: 生成的回复。
        target: 群友中位长度（提示用）。
        ceiling: 超长线，超过即认为比普通一句话明显长。
    """

    stripped = (text or "").strip()
    length = len(stripped)
    points = count_points(stripped)
    if length > ceiling:
        return (
            f"过长({length}字，群里普通一句话不超过{ceiling}字)",
            f"群里大家一句话一般 {target} 字左右。这次只挑一个最想说的点，用平常说话的长度说出来；"
            "其他点直接不说，不要把几层意思压缩进一句。",
        )
    if points >= 3 and length > target:
        return (
            f"信息点过多({points}个)",
            "一句话里塞了好几层意思。只保留一个点，像随口接话那样说，其余全部删掉。",
        )
    return None


def density_prompt_line(target: int) -> str:
    """注入回复提示词的一行。"""

    return (
        f"这个群大家一句话通常 {target} 字左右，你也一样，宁可短不要长：一次只说一个点，"
        "想说的多就挑最想说的那个，剩下的不说；不要为了短而把几层意思压缩成一句。"
    )
