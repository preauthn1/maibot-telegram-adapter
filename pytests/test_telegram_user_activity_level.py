"""活跃度参数的安全边界测试（封禁后修订版）。

历史：2026-08-31 为提高活跃度，把参与率上限提到 0.45、发言间隔
降到 9s、权重下限提到 0.6、基准倍率提到 1.4，结果当天 15 时
单小时出站 107 条，账号被 Telegram 反垃圾系统限制
（SpamBot: "your account was limited"）。

教训：局部参数各自合规不代表全局安全。这个文件现在锁定的是
**上界**（防止再次调过头），全局总量由 send_budget 负责。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter import small_chat as sc  # noqa: E402
from telegram_user_adapter.small_chat import SmallChatModerator  # noqa: E402


def test_reply_ratio_stays_conservative() -> None:
    """参与率上限不得回到触发封禁的 0.45，但也不必压到反常沉默。

    实测真人单群小时峰值 68.9~80 条，0.25 偏紧；
    跨多群并发这个真正的异常由 attention_focus 负责。
    """

    assert 0.30 <= sc.SMALL_CHAT_REPLY_RATIO <= 0.40


def test_min_reply_gap_restored() -> None:
    """发言间隔不得回到 9s，但真人在单群内连续接话可以更快。

    9s 配合 12 群并发导致封禁；现在并发已由 attention_focus 限制，
    单群内 14s 仍高于"读完+思考+打字"的物理下限。
    """

    assert 12.0 <= sc.MIN_REPLY_GAP_SECONDS <= 18.0


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
