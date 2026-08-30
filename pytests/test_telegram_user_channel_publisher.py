"""频道发布节奏测试。

核心要求：**发布时间不能有规律**。定时发帖是最明显的自动化特征，
比内容本身更容易暴露。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.channel_publisher import (  # noqa: E402
    CN_TZ,
    ChannelPost,
    ChannelPublisher,
    select_valuable_messages,
)


def _at(hour: int, minute: int = 0) -> datetime:
    """构造一个北京时间。"""

    return datetime(2026, 8, 31, hour, minute, tzinfo=CN_TZ)


def test_quiet_hours_blocked() -> None:
    """凌晨不发帖——连续熬夜发布不像真人作息。"""

    p = ChannelPublisher()
    for hour in (2, 4, 6, 7):
        decision = p.can_publish(now=_at(hour))
        assert not decision.allowed, f"{hour}点不该允许发布"


def test_daytime_allowed() -> None:
    """正常时段允许发布。"""

    p = ChannelPublisher()
    assert p.can_publish(now=_at(14)).allowed


def test_daily_quota_enforced() -> None:
    """每日配额是硬上限，频道一天刷十几条不正常。"""

    p = ChannelPublisher(daily_quota=2, min_interval=0.0)
    post = ChannelPost(text="x")

    t = 0.0
    for _ in range(2):
        assert p.can_publish(now=_at(14), monotonic_now=t).allowed
        p.mark_published(post, monotonic_now=t)
        t += 10.0

    assert not p.can_publish(now=_at(14), monotonic_now=t).allowed


def test_quota_resets_next_day() -> None:
    """跨天后配额重置。"""

    p = ChannelPublisher(daily_quota=1, min_interval=0.0)
    p.can_publish(now=_at(14), monotonic_now=0.0)
    p.mark_published(ChannelPost(text="x"), monotonic_now=0.0)
    assert not p.can_publish(now=_at(15), monotonic_now=1.0).allowed

    tomorrow = _at(14) + timedelta(days=1)
    assert p.can_publish(now=tomorrow, monotonic_now=2.0).allowed


def test_min_interval_enforced() -> None:
    """两次发布之间要有间隔，不能连着刷。"""

    p = ChannelPublisher(daily_quota=10, min_interval=3600.0)
    p.mark_published(ChannelPost(text="x"), monotonic_now=1000.0)

    assert not p.can_publish(now=_at(14), monotonic_now=1500.0).allowed
    assert p.can_publish(now=_at(14), monotonic_now=1000.0 + 3601.0).allowed


def test_delay_is_randomized() -> None:
    """⚠️ 最关键的一条：发布延迟必须随机，否则时间有规律=暴露。"""

    p = ChannelPublisher(delay_min=300.0, delay_max=5400.0)
    delays = {p.can_publish(now=_at(14)).delay_seconds for _ in range(30)}

    # 30 次采样应当得到多个不同值
    assert len(delays) > 20, f"延迟不够随机，只有 {len(delays)} 种取值"
    assert all(300.0 <= d <= 5400.0 for d in delays)


def test_forward_only_from_allowed_chats() -> None:
    """原生转发会带 Forwarded from，会公开我们潜伏在哪些群。"""

    p = ChannelPublisher(forwardable_chats={"-100public"})

    ok = ChannelPost(text="x", source_chat_id="-100public", source_message_id=5, forward=True)
    assert p.should_forward(ok)

    # 未列入白名单的群绝不原生转发
    private = ChannelPost(text="x", source_chat_id="-100secret", source_message_id=5, forward=True)
    assert not p.should_forward(private)


def test_forward_requires_explicit_flag() -> None:
    """没显式要求转发时，即使来源可转发也不转。"""

    p = ChannelPublisher(forwardable_chats={"-100public"})
    post = ChannelPost(text="x", source_chat_id="-100public", source_message_id=5, forward=False)
    assert not p.should_forward(post)


def test_duplicate_detection() -> None:
    """同一条来源消息不该发两次。"""

    p = ChannelPublisher()
    post = ChannelPost(text="x", source_chat_id="-100A", source_message_id=42)

    assert not p.is_duplicate(post)
    p.mark_published(post, monotonic_now=0.0)
    assert p.is_duplicate(post)


def test_selection_filters_low_value() -> None:
    """低价值内容不转发——频道全是垃圾本身也是暴露。"""

    msgs = [
        {"text": "嗯"},                          # 太短
        {"text": "https://example.com/x"},       # 纯链接
        {"text": "[图片]"},                       # 纯附件
        {"text": "这个方案的关键在于把状态机和路由分层，避免耦合导致难以测试"},  # 有价值
    ]
    picked = select_valuable_messages(msgs)
    assert len(picked) == 1
    assert "状态机" in picked[0]["text"]


def test_selection_respects_limit() -> None:
    """选取数量有上限。"""

    msgs = [{"text": "这是一条足够长的有价值内容用来测试选取上限逻辑是否正确"} for _ in range(10)]
    assert len(select_valuable_messages(msgs, limit=3)) == 3


def test_stats_exposed() -> None:
    """状态可查，便于排查。"""

    p = ChannelPublisher(daily_quota=4)
    p.can_publish(now=_at(14), monotonic_now=0.0)
    p.mark_published(ChannelPost(text="x"), monotonic_now=0.0)

    s = p.stats()
    assert s["posted_today"] == 1
    assert s["quota"] == 4
