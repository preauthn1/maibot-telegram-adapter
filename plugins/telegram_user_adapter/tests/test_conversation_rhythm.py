"""关键拟人化节奏闸门的回归测试。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from telegram_user_adapter.share_guard import ShareGuard
from telegram_user_adapter.small_chat import SmallChatModerator

TZ = timezone(timedelta(hours=8))


def test_share_guard_blocks_when_bot_owns_over_twenty_percent_of_busy_window():
    guard = ShareGuard(window_minutes=10, max_share=0.20, min_samples=10)
    base = datetime(2026, 9, 20, 12, 0, tzinfo=TZ)

    for second in range(8):
        guard.note_inbound(base + timedelta(seconds=second))
    for second in range(8, 10):
        guard.note_outbound(base + timedelta(seconds=second))

    assert guard.current_share(base + timedelta(seconds=10)) == 0.20
    assert guard.allows_send(base + timedelta(seconds=10))

    guard.note_outbound(base + timedelta(seconds=11))
    assert not guard.allows_send(base + timedelta(seconds=12))
    assert "话语权占比过高" in (guard.describe_block(base + timedelta(seconds=12)) or "")


def test_share_guard_complaint_silence_overrides_low_share():
    guard = ShareGuard(complaint_silence_minutes=45)
    base = datetime(2026, 9, 20, 12, 0, tzinfo=TZ)
    guard.silence_until_minutes = lambda: 45.0  # deterministic test only

    guard.note_complaint(base)
    assert not guard.allows_send(base + timedelta(minutes=44, seconds=59))
    assert "被投诉后静默中" in (guard.describe_block(base + timedelta(minutes=1)) or "")
    assert guard.allows_send(base + timedelta(minutes=45))


def test_profile_gap_applies_to_directed_messages_too():
    moderator = SmallChatModerator(min_gap=14.0)
    moderator.record_outbound("chat", "先发一句", now=100.0)

    suppressed, reason = moderator.should_suppress(
        "chat", member_count=100, is_directed=True, now=120.0, min_gap_override=55.0
    )
    assert not suppressed, reason

    # Direct messages remain eligible: the hard complaint silence belongs to
    # ShareGuard, not to the ordinary rhythm guard.
    suppressed, reason = moderator.should_suppress(
        "chat", member_count=100, is_directed=True, now=101.0, min_gap_override=55.0
    )
    assert not suppressed, reason
