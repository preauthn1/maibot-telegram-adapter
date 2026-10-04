"""回复信息密度对齐（让我们的一句话和群友一句话装的信息差不多）。

问题：单纯压字数上限，模型会把原本两三句的内容挤进一句，信息密度反而远高于人。
正确做法是**减少要说的点**，而不是压缩表达。

做法：
1. 目标长度来自当前聊天流最近群友发言的中位数（动态、按会话），而不是固定数字。
2. 提示词里给出这个具体数字，并明确"只说一个点；想说的多就挑一个，其余不说"。
3. 生成后若明显超长（> 目标×2.2 且 > 目标+12），或一句里塞了多个信息点
   （多个分句/列举），触发重生成，约束是"删掉要点"而不是"缩写"。
"""

from statistics import median
from typing import Iterable, Optional, Tuple

import re

DEFAULT_TARGET = 14
MIN_TARGET = 6
MAX_TARGET = 30
_CLAUSE_SPLIT = re.compile(r"[，,；;。！!？?…]+|\s{2,}")
_LIST_MARK = re.compile(r"(?:^|\s)(?:\d+[.、)]|[-•·])\s*|首先|其次|另外|而且还|此外|总之")


def target_length(peer_texts: Iterable[str]) -> int:
    """当前聊天群友最近发言的中位长度，裁剪到 [6, 30]（用于提示词）。"""

    lengths = [len(text.strip()) for text in peer_texts if text and text.strip()]
    if len(lengths) < 5:
        return DEFAULT_TARGET
    return int(max(MIN_TARGET, min(MAX_TARGET, round(median(lengths)))))


def length_ceiling(peer_texts: Iterable[str]) -> int:
    """群友最近发言长度的 P85：人本身也有长短，只截我们比大多数人都长的尾巴。"""

    lengths = sorted(len(text.strip()) for text in peer_texts if text and text.strip())
    if len(lengths) < 5:
        return DEFAULT_TARGET * 2
    index = min(len(lengths) - 1, int(len(lengths) * 0.85))
    return max(12, min(60, lengths[index]))


def count_points(text: str) -> int:
    """粗估一条回复里的信息点数：分句数 + 列举标记。语气词短分句不计。"""

    clauses = [c for c in _CLAUSE_SPLIT.split(text or "") if len(c.strip()) >= 4]
    return len(clauses) + len(_LIST_MARK.findall(text or ""))


def density_violation(text: str, target: int, ceiling: int) -> Optional[Tuple[str, str]]:
    """返回 (原因, 重生成约束)；未违规返回 None。

    Args:
        text: 生成的回复。
        target: 群友中位长度（提示用）。
        ceiling: 群友 P85 长度，超过即认为比大多数人都长。
    """

    stripped = (text or "").strip()
    length = len(stripped)
    points = count_points(stripped)
    if length > ceiling:
        return (
            f"过长({length}字，群里八成发言不超过{ceiling}字)",
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
        f"这个群大家一句话通常 {target} 字左右。你也一样：一次只说一个点，"
        "想说的多就挑最想说的那个，剩下的不说；不要为了短而把几层意思压缩成一句。"
    )
