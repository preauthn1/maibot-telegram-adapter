"""发言前自检：用已积累的教训拦住重犯。

为什么需要这个模块
------------------

现有 ``self_improvement`` 是**事后学习**：发出去之后观察有没有
被接话、有没有被质疑，再把教训写进 SKILL.md。这条闭环是必要的，
但对"不被识破"这件事来说太晚——2026-08-31 账号因用户举报被封，
等到"事后"账号已经没了。

借鉴 Hermes 的做法：**动手之前先加载相关知识**。Hermes 在执行
任务前会从技能索引里挑出相关条目读进来，而不是做完再复盘。
高风险操作也是先自检再执行。

这里把该思路落成「发言前自检」——把 SKILL.md 里记录的失败模式
在**发言前**匹配一遍，命中就拦下。两条闭环的分工：

- ``self_improvement.record_outcome`` → 事后，从后果里学
- ``pre_send_review.review_draft``    → 事前，用学到的拦住重犯

教训用 Markdown 存储，沿用画像卡的人可读格式：反引号包裹的
条目视为匹配模式，其余正文只给人看。这样人能直接翻阅、修改，
也能被程序解析。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

import re

# 匹配 Markdown 列表项里被反引号包裹的模式，例如：
#   - `作为一个 AI`：直接暴露身份
_PATTERN_LINE = re.compile(r"^\s*[-*]\s*`([^`]+)`")

# 只在这个标题下的内容里取模式。
#
# 为什么必须限定段落：self_improvement 会把"被怀疑"的记录也写进
# SKILL.md，格式形如
#     - `2026-08-31T11:03:07+08:00` 群 `-100xxxxxxxxx`：
# 若全文扫描，时间戳和群号会被当成匹配模式——讨论群号时就被误拦。
_SECTION_TITLE = "禁用表达"


@dataclass(frozen=True)
class ReviewVerdict:
    """自检结论。

    Attributes:
        allowed: 是否放行。
        reason: 人类可读的说明。
        matched: 命中的模式；未命中为 None。
    """

    allowed: bool
    reason: str = ""
    matched: Optional[str] = None


class LessonStore:
    """已积累的失败模式集合。"""

    def __init__(self, *, patterns: Sequence[str] = ()) -> None:
        """初始化教训库。

        Args:
            patterns: 失败模式列表，匹配时统一按小写比较。
        """

        self.patterns: Tuple[str, ...] = tuple(
            item.strip().lower() for item in patterns if item.strip()
        )

    @classmethod
    def from_markdown(cls, text: str) -> "LessonStore":
        """从 Markdown 文本解析教训。

        只扫描「禁用表达」标题下的区块，且只把列表项里反引号包裹的
        内容当作匹配模式；其余正文视为给人看的说明。

        限定段落是必须的：``self_improvement`` 会把被怀疑的记录也
        写进同一份 SKILL.md，其中的时间戳和群号同样带反引号，
        全文扫描会把它们当成模式，导致讨论群号时被误拦。

        Args:
            text: Markdown 文本。

        Returns:
            LessonStore: 解析出的教训库。
        """

        found = []
        in_section = False
        for line in text.splitlines():
            stripped = line.strip()

            if stripped.startswith("#"):
                # 进入或离开目标段落。同级/更高级标题都视为离开。
                in_section = _SECTION_TITLE in stripped
                continue

            if not in_section:
                continue

            match = _PATTERN_LINE.match(line)
            if match is not None:
                found.append(match.group(1))
        return cls(patterns=found)

    def find_match(self, text: str) -> Optional[str]:
        """返回文本命中的第一个模式。

        Args:
            text: 待检查文本。

        Returns:
            Optional[str]: 命中的模式；未命中返回 None。
        """

        lowered = text.lower()
        for pattern in self.patterns:
            if pattern in lowered:
                return pattern
        return None


def review_draft(text: str, *, store: LessonStore) -> ReviewVerdict:
    """在发言前检查草稿是否命中已知失败模式。

    Args:
        text: 待发送的文本。
        store: 教训库。

    Returns:
        ReviewVerdict: 自检结论。
    """

    if not text.strip():
        return ReviewVerdict(allowed=True)

    hit = store.find_match(text)
    if hit is None:
        return ReviewVerdict(allowed=True)

    return ReviewVerdict(
        allowed=False,
        reason=f"命中已记录的失败模式 {hit!r}",
        matched=hit,
    )
