"""群权重与作息倍率的乘法叠加边界测试。

线上实测：7 次权重写回中 6 次是 0.22。拆解后是
零互动基线 0.40 × 当前时段作息 0.562 = 0.225，
意味着"没人 @ 我们"的群发言频率被压到 22%。

这会把参与率上限、退避时长等其他活跃度参数的提升几乎全抵消掉。
本测试锁定叠加后的下限，避免多层压制无意识地相乘到过低。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter import engagement as eng  # noqa: E402
from telegram_user_adapter import human_rhythm as rhythm  # noqa: E402
from telegram_user_adapter.engagement import ChatEngagementTracker  # noqa: E402


def test_idle_baseline_not_over_suppressed() -> None:
    """零互动基线不应低于 0.55：低于此值账号会显得反常沉默。"""

    assert eng.MIN_MULTIPLIER >= 0.55


def test_combined_floor_stays_usable() -> None:
    """基线与作息最低点相乘后仍需保持可用发言能力。

    两者是乘法关系，各自看着合理、相乘后可能过低。
    这里用作息模块自身的倍率下限做最坏情况检查。
    """

    combined = eng.MIN_MULTIPLIER * rhythm.MIN_MULTIPLIER

    assert combined >= 0.08, f"最坏情况倍率 {combined:.3f} 过低"


def test_engagement_still_lifts_weight() -> None:
    """多人互动仍应显著抬升权重，压制放宽不等于取消区分度。"""

    tracker = ChatEngagementTracker()
    chat = "-1009000000001"
    idle = tracker.compute_multiplier(chat)

    for index in range(3):
        tracker.record_engagement(chat, f"user{index}")
    engaged = tracker.compute_multiplier(chat)

    assert engaged > idle * 1.5


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
