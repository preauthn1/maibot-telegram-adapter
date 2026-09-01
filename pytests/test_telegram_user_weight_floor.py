"""权重乘法叠加边界测试（封禁后修订版）。

历史上这个文件锁定 MIN_MULTIPLIER >= 0.55，理由是"冷群倍率 0.22
压制过度"。但 2026-08-31 把下限提到 0.6、基准提到 1.4 后，
当天出站 533 条、峰值 107 条/小时，账号被 Telegram 反垃圾限制。

修订后的立场：乘法叠加确实要防"意外相乘到极低"，但更要防
"整体过于活跃"。因此同时锁上下界，并把全局总量交给 send_budget。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter import engagement as eng  # noqa: E402
from telegram_user_adapter import human_rhythm as rhythm  # noqa: E402
from telegram_user_adapter.engagement import ChatEngagementTracker  # noqa: E402


def test_idle_baseline_within_safe_band() -> None:
    """零互动基线需落在合理区间：过低显得反常，过高触发风控。"""

    assert 0.4 <= eng.MIN_MULTIPLIER <= 0.6


def test_base_multiplier_bounded() -> None:
    """基准倍率不得回到 1.4（导致封禁），但单群场景可用到区间上限。

    真人实测单群小时峰值最高 80 条、前 10 名平均 68.9 条，
    因此 1.2 仍在真人量级内。

    上限 1.2 的依据：导致封禁的 1.4 是在 12 群并发下发生的，
    真正的异常是并发会话数（真人跨 ≥3 群为 0/1128），
    该维度现由 attention_focus 独立拦截。
    """

    assert 1.0 <= eng.BASE_MULTIPLIER <= 1.2


def test_combined_floor_not_degenerate() -> None:
    """基线与作息最低点相乘后不应低到形同静音。"""

    combined = eng.MIN_MULTIPLIER * rhythm.MIN_MULTIPLIER

    assert combined >= 0.05, f"最坏情况倍率 {combined:.3f} 过低"


def test_engagement_still_lifts_weight() -> None:
    """多人互动仍应抬升权重，保留区分度。"""

    tracker = ChatEngagementTracker()
    chat = "-1009000000001"
    idle = tracker.compute_multiplier(chat)

    for index in range(3):
        tracker.record_engagement(chat, f"user{index}")

    assert tracker.compute_multiplier(chat) > idle


def test_single_user_flood_still_capped() -> None:
    """单人刷 @ 仍需被压住，防的是刷 token。"""

    tracker = ChatEngagementTracker()
    solo = "-1009000000002"
    diverse = "-1009000000003"

    for _ in range(20):
        tracker.record_engagement(solo, "spammer")
    for index in range(3):
        tracker.record_engagement(diverse, f"user{index}")

    assert tracker.compute_multiplier(solo) < tracker.compute_multiplier(diverse)
