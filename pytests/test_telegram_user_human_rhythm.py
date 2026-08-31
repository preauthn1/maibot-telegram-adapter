"""真人作息曲线测试。

目标：让发言时段分布贴近真人。实测账号 95% 发言挤在 07-09 点，
而同群 327 个真人这三小时只占 20%——这种\"每天固定时段集中说话\"
的模式比说错话更容易暴露。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.human_rhythm import (  # noqa: E402
    CN_TZ,
    MAX_MULTIPLIER,
    MIN_MULTIPLIER,
    get_activity_multiplier,
)


def _at(hour: int, minute: int = 0, day: int = 31) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=CN_TZ)


def test_deep_night_heavily_suppressed() -> None:
    """⚠️ 凌晨 3-5 点真人几乎全睡了，我们必须压到极低。"""

    for hour in (3, 4, 5):
        mult = get_activity_multiplier(_at(hour))
        assert mult < 0.2, f"{hour} 点倍率 {mult} 太高，深夜发言最容易暴露"


def test_evening_peak_is_active() -> None:
    """真人高峰在傍晚到深夜，这时应当更愿意说话。"""

    for hour in (17, 21):
        assert get_activity_multiplier(_at(hour)) > 1.0


def test_morning_not_over_active() -> None:
    """早 8 点是我们原本的畸形高峰（33%），真人只有 4.7%。
    调整后不该再是全天最活跃的时段。"""

    morning = get_activity_multiplier(_at(8))
    evening = get_activity_multiplier(_at(21))
    assert morning < evening, "早高峰仍然压过晚高峰，作息没有纠正"


def test_multiplier_within_bounds() -> None:
    """倍率必须落在配置区间内。"""

    for hour in range(24):
        mult = get_activity_multiplier(_at(hour))
        assert 0.0 < mult <= MAX_MULTIPLIER
        # 深夜档走独立系数，不受 MIN_MULTIPLIER 约束
        assert mult >= 0.05


def test_never_fully_silent() -> None:
    """不设为 0——完全静音会形成\"精确到点开关机\"的规律，
    真人偶尔也会半夜冒一句。"""

    for hour in range(24):
        assert get_activity_multiplier(_at(hour)) > 0.0


def test_daily_jitter_shifts_schedule() -> None:
    """作息要有跨天抖动，否则每天完全相同同样是规律。"""

    values = {
        round(get_activity_multiplier(_at(14, day=d)), 4)
        for d in range(1, 15)
    }
    assert len(values) > 1, "跨天倍率完全一致，缺少作息抖动"


def test_jitter_stable_within_same_day() -> None:
    """同一天内偏移必须稳定，否则同一小时反复抖动没有意义。"""

    a = get_activity_multiplier(_at(14, 0))
    b = get_activity_multiplier(_at(14, 1))
    # 同小时同天，允许分钟推进带来的曲线平移，但不该跳变
    assert abs(a - b) < 0.35


def test_schedule_matches_human_shape() -> None:
    """整体形状要贴近真人：晚间总量应高于凌晨。"""

    night = sum(get_activity_multiplier(_at(h)) for h in (2, 3, 4, 5))
    evening = sum(get_activity_multiplier(_at(h)) for h in (17, 20, 21, 22))
    assert evening > night * 3, "作息曲线没有体现真人的昼夜差异"
