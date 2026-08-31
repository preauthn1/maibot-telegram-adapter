"""talk_value 提升诉求的结论记录（封禁后修订版）。

用户要求把 talk_value 从 1.0 提到 1.3~1.5。实测两点：

1. 主程序 ``talk_value`` 被 Pydantic 限制在 ge=0/le=1，
   当前 1.0 已是硬上限，填 1.1 直接被校验拒绝。
2. 走等效路径（把 engagement.BASE_MULTIPLIER 提到 1.4）后，
   2026-08-31 当天出站 533 条、15 时峰值 107 条/小时，
   账号被 Telegram 反垃圾系统限制。

结论：**1.3~1.5 这个量级对真人号不可行**。诉求本身合理
（账号确实太沉默），但正确解法是提高"该说话时说得上"的命中率，
而不是整体抬高发言频率。本文件锁定不要再走回头路。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter import engagement as eng  # noqa: E402
from telegram_user_adapter.engagement import ChatEngagementTracker  # noqa: E402


def test_talk_value_equivalent_stays_safe() -> None:
    """基准倍率不得再回到 1.3~1.5：已实测会触发账号限制。"""

    assert eng.BASE_MULTIPLIER < 1.3


def test_max_multiplier_bounded() -> None:
    """上限保留抬升空间，但不应无限放大。"""

    assert eng.BASE_MULTIPLIER < eng.MAX_MULTIPLIER <= 2.0


def test_engaged_chat_gets_more_than_idle() -> None:
    """有人互动的群仍应比冷群更积极——区分度是核心价值。"""

    tracker = ChatEngagementTracker()
    engaged = "-1009000000007"
    for index in range(3):
        tracker.record_engagement(engaged, f"user{index}")

    assert tracker.compute_multiplier(engaged) > tracker.compute_multiplier("-1009000000008")


def test_single_user_flood_still_capped() -> None:
    """抬升区分度不能破坏防刷 token 的能力。"""

    tracker = ChatEngagementTracker()
    solo = "-1009000000009"
    diverse = "-1009000000010"

    for _ in range(20):
        tracker.record_engagement(solo, "spammer")
    for index in range(3):
        tracker.record_engagement(diverse, f"user{index}")

    assert tracker.compute_multiplier(solo) < tracker.compute_multiplier(diverse)
