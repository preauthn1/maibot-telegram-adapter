"""活跃度提升测试。

线上实测整体参与率仅 6.9%（配置上限 30%），压制主要来自：
- 95 次「距上次发言不足 12 秒」
- 33 次「参与率已超上限」

提升活跃度的同时必须守住反识破底线：`MIN_REPLY_GAP_SECONDS` 和
阅读延迟是账号被当面质问 "ai？" 之后加的防护，不能为了活跃而回退。
本测试锁定"可以更活跃、但不能秒回"这条边界。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter import small_chat as sc  # noqa: E402
from telegram_user_adapter.small_chat import SmallChatModerator  # noqa: E402


def test_reply_ratio_allows_more_participation() -> None:
    """参与率上限应高于线上实测的 6.9%，给出提升空间。"""

    assert sc.SMALL_CHAT_REPLY_RATIO >= 0.40


def test_min_reply_gap_still_blocks_instant_reply() -> None:
    """最小发言间隔不得低于 8 秒：秒回是被识破的直接原因。"""

    assert sc.MIN_REPLY_GAP_SECONDS >= 8.0


def test_read_delay_floor_preserved() -> None:
    """阅读延迟下限必须保留，人读完一句话不可能不到 3 秒。"""

    assert sc.READ_DELAY_MIN_SECONDS >= 3.0


def test_directed_message_bypasses_ratio_cap() -> None:
    """被 @ 时不应因参与率上限而沉默——真人被问到会答。"""

    moderator = SmallChatModerator()
    for _ in range(50):
        moderator.record_inbound("chat-a")
    for _ in range(40):
        moderator.record_outbound("chat-a", "嗯")

    suppressed, _ = moderator.should_suppress(
        "chat-a",
        member_count=5,
        is_directed=True,
    )

    assert suppressed is False


def test_ratio_cap_still_enforced_for_undirected() -> None:
    """非定向消息在超出上限后仍需压制，避免变成刷屏机器人。"""

    moderator = SmallChatModerator()
    for _ in range(20):
        moderator.record_inbound("chat-b")
    for _ in range(20):
        moderator.record_outbound("chat-b", "嗯")
    moderator._states["chat-b"].last_reply_at = 0.0

    suppressed, reason = moderator.should_suppress(
        "chat-b",
        member_count=5,
        is_directed=False,
    )

    assert suppressed is True
    assert "参与率" in reason
