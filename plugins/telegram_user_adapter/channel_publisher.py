"""频道内容发布。

把有价值的群聊内容整理后发到自己的频道（@testchannel）。

**核心约束：不能因为发频道而暴露是机器人。** 具体体现为：

1. **绝不定时发布**。整点/半点/固定间隔发帖是最明显的自动化特征。
   这里用"随机延迟 + 每日配额 + 最小间隔"三层控制，让发布时间看起来
   像人想起来才发。
2. **静默时段不发**。凌晨 2-7 点连续发帖不像真人作息。
3. **转发要挑来源**。原生转发会带 "Forwarded from"，等于公开自己
   潜伏在哪些群。只转公开群，私密群一律只做无署名摘要。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

import random

CN_TZ = timezone(timedelta(hours=8))

# 每日发布上限。频道是个人性质的，一天刷十几条不正常。
DEFAULT_DAILY_QUOTA = 4

# 两次发布之间的最小间隔（秒）。避免连着刷屏。
DEFAULT_MIN_INTERVAL = 3600.0

# 发布前的随机延迟范围（秒）。打散时间，避免"消息一出现就转发"。
DEFAULT_DELAY_MIN = 300.0
DEFAULT_DELAY_MAX = 5400.0

# 不发布的时段（北京时间）。凌晨连续发帖不像真人。
QUIET_START = dt_time(2, 0)
QUIET_END = dt_time(7, 30)


@dataclass
class ChannelPost:
    """一条待发布内容。"""

    text: str
    """要发布的正文。"""

    source_chat_id: str = ""
    """来源会话，用于判断能否原生转发。"""

    source_message_id: Optional[int] = None
    """来源消息 ID；提供时可走原生转发。"""

    forward: bool = False
    """是否使用原生转发（会带 Forwarded from）。"""


@dataclass
class PublishDecision:
    """一次发布决策的结果。"""

    allowed: bool
    """是否允许发布。"""

    reason: str = ""
    """不允许时的原因，仅用于日志。"""

    delay_seconds: float = 0.0
    """允许时建议的随机延迟。"""


@dataclass
class ChannelPublisher:
    """频道发布节奏控制。

    只负责"能不能发、什么时候发"，实际发送由调用方完成——
    这样便于单测，也让 Telethon 细节留在客户端层。
    """

    daily_quota: int = DEFAULT_DAILY_QUOTA
    min_interval: float = DEFAULT_MIN_INTERVAL
    delay_min: float = DEFAULT_DELAY_MIN
    delay_max: float = DEFAULT_DELAY_MAX
    # 允许原生转发的来源会话（公开群）。不在此列的只做无署名摘要。
    forwardable_chats: Set[str] = field(default_factory=set)

    _posted_today: int = 0
    _quota_date: Optional[str] = None
    _last_post_at: Optional[float] = None
    _published_sources: Set[str] = field(default_factory=set)

    def _reset_quota_if_needed(self, now: datetime) -> None:
        """跨天时重置配额。"""

        today = now.strftime("%Y-%m-%d")
        if self._quota_date != today:
            self._quota_date = today
            self._posted_today = 0
            # 跨天同时清理去重集合，避免无限增长。
            self._published_sources.clear()

    def can_publish(
        self, *, now: Optional[datetime] = None, monotonic_now: Optional[float] = None
    ) -> PublishDecision:
        """判断当前是否可以发布。

        Args:
            now: 当前时间（北京时区）。省略则取系统时间。
            monotonic_now: 单调时钟读数，用于间隔判断。

        Returns:
            PublishDecision: 决策结果。
        """

        current = now or datetime.now(CN_TZ)
        self._reset_quota_if_needed(current)

        # 静默时段：凌晨连续发帖不像真人作息。
        current_time = current.time()
        if QUIET_START <= current_time < QUIET_END:
            return PublishDecision(False, "静默时段")

        if self._posted_today >= self.daily_quota:
            return PublishDecision(False, f"已达每日上限({self.daily_quota})")

        if monotonic_now is not None and self._last_post_at is not None:
            elapsed = monotonic_now - self._last_post_at
            if elapsed < self.min_interval:
                return PublishDecision(
                    False, f"距上次发布仅 {elapsed:.0f}s，未满 {self.min_interval:.0f}s"
                )

        # 随机延迟：让发布时间显得是"想起来才发"，而不是被事件触发。
        delay = random.uniform(self.delay_min, self.delay_max)
        return PublishDecision(True, "", delay)

    def should_forward(self, post: ChannelPost) -> bool:
        """判断这条内容能否用原生转发。

        原生转发会带 "Forwarded from 群名"，等于公开自己潜伏在哪些群。
        只有明确标记为可转发的公开群才允许。

        Args:
            post: 待发布内容。

        Returns:
            bool: 可以原生转发时返回 ``True``。
        """

        if not post.forward or post.source_message_id is None:
            return False
        return post.source_chat_id in self.forwardable_chats

    def is_duplicate(self, post: ChannelPost) -> bool:
        """判断这条内容是否已经发过。

        Args:
            post: 待发布内容。

        Returns:
            bool: 已发布过时返回 ``True``。
        """

        key = self._source_key(post)
        return key in self._published_sources if key else False

    def mark_published(self, post: ChannelPost, *, monotonic_now: float) -> None:
        """记录一次成功发布。

        Args:
            post: 已发布内容。
            monotonic_now: 单调时钟读数。
        """

        self._posted_today += 1
        self._last_post_at = monotonic_now
        key = self._source_key(post)
        if key:
            self._published_sources.add(key)

    @staticmethod
    def _source_key(post: ChannelPost) -> str:
        """生成来源去重键。"""

        if post.source_chat_id and post.source_message_id is not None:
            return f"{post.source_chat_id}:{post.source_message_id}"
        return ""

    def stats(self) -> Dict[str, Any]:
        """导出当前状态，便于排查。

        Returns:
            Dict[str, Any]: 状态字典。
        """

        return {
            "posted_today": self._posted_today,
            "quota": self.daily_quota,
            "quota_date": self._quota_date,
            "tracked_sources": len(self._published_sources),
        }


def select_valuable_messages(
    messages: List[Dict[str, Any]], *, min_length: int = 20, limit: int = 3
) -> List[Dict[str, Any]]:
    """从群聊消息里挑出值得转发的高价值内容。

    判断标准刻意保守——宁可少发，不可发垃圾。频道内容质量差
    本身也是一种暴露（真人不会转发无意义的闲聊）。

    门槛取 20 字：中文信息密度高，20 字已经能表达一个完整观点，
    再高会把大量有价值的短评论挡在外面。

    Args:
        messages: 候选消息，每项含 ``text`` 与可选的 ``sender_id``。
        min_length: 最短长度门槛。
        limit: 最多返回几条。

    Returns:
        List[Dict[str, Any]]: 选中的消息。
    """

    selected: List[Dict[str, Any]] = []
    for item in messages:
        text = str(item.get("text", "")).strip()
        if len(text) < min_length:
            continue
        # 纯链接、纯表情、纯附件提示都没有转发价值。
        if text.startswith("http") and " " not in text:
            continue
        if text.startswith("[") and text.endswith("]"):
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected
