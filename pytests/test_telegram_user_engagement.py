"""群权重调度测试。

核心要求：**单个人刷屏顶不高群权重**。
权重看的是\"有多少不同的人在跟我们互动\"，不是消息总量——
否则刷 token 的人只要狂发 @ 就能让 bot 疯狂推理。
"""

from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.engagement import (  # noqa: E402
    MAX_MULTIPLIER,
    MIN_MULTIPLIER,
    ChatEngagementTracker,
)


def test_no_engagement_gives_min_multiplier() -> None:
    """没人互动的群应当降到最低权重，省下推理。"""

    t = ChatEngagementTracker()
    assert t.compute_multiplier("-100quiet") == MIN_MULTIPLIER


def test_single_user_spam_cannot_max_weight() -> None:
    """关键防刷：一个人狂刷 100 次也顶不满权重。"""

    t = ChatEngagementTracker()
    for _ in range(100):
        t.record_engagement("-100spam", "attacker")

    mult = t.compute_multiplier("-100spam")
    # 多样性只有 1/3，拿不到满分
    assert mult < MAX_MULTIPLIER * 0.8, f"单人刷屏拿到了 {mult}，防刷失效"


def test_diverse_engagement_raises_weight() -> None:
    """多人真实互动应当显著提高权重。"""

    t = ChatEngagementTracker()
    for uid in ["alice", "bob", "carol", "dave"]:
        for _ in range(5):
            t.record_engagement("-100active", uid)

    mult = t.compute_multiplier("-100active")
    assert mult > 1.5, f"多人互动只拿到 {mult}"


def test_diverse_beats_single_spammer() -> None:
    """同样的消息量，多人互动的权重必须高于单人刷屏。"""

    t = ChatEngagementTracker()

    # 群A：1 个人发 20 次
    for _ in range(20):
        t.record_engagement("-100A", "spammer")

    # 群B：4 个人各发 5 次（总量相同）
    for uid in ["u1", "u2", "u3", "u4"]:
        for _ in range(5):
            t.record_engagement("-100B", uid)

    a = t.compute_multiplier("-100A")
    b = t.compute_multiplier("-100B")
    assert b > a, f"单人刷屏({a}) 不该 >= 多人互动({b})"


def test_multiplier_stays_in_bounds() -> None:
    """倍率必须始终落在配置区间内。"""

    t = ChatEngagementTracker()
    for i in range(200):
        t.record_engagement("-100X", f"user{i}")

    mult = t.compute_multiplier("-100X")
    assert MIN_MULTIPLIER <= mult <= MAX_MULTIPLIER


def test_weights_are_per_chat() -> None:
    """一个群的热度不该影响另一个群。"""

    t = ChatEngagementTracker()
    for uid in ["a", "b", "c"]:
        t.record_engagement("-100hot", uid)

    assert t.compute_multiplier("-100hot") > MIN_MULTIPLIER
    assert t.compute_multiplier("-100cold") == MIN_MULTIPLIER


def test_should_apply_skips_tiny_changes() -> None:
    """微小变化不写回 Host，避免频繁调用能力接口。"""

    t = ChatEngagementTracker()
    t.record_engagement("-100X", "a")
    m = t.compute_multiplier("-100X")

    assert t.should_apply("-100X", m)  # 首次必写
    t.mark_applied("-100X", m)
    assert not t.should_apply("-100X", m + 0.01)  # 变化太小
    assert t.should_apply("-100X", m + 0.5)  # 变化够大


def test_window_pruning_bounds_memory() -> None:
    """窗口外事件要被丢弃，长期运行不能无限膨胀。"""

    t = ChatEngagementTracker(window_seconds=0.0)
    for i in range(50):
        t.record_engagement("-100X", f"u{i}")

    # 窗口为 0，所有事件立即过期
    snap = t.snapshot()
    assert snap.get("-100X", {}).get("events", 0) <= 1


def test_snapshot_exposes_metrics() -> None:
    """快照要能看出事件数、去重人数和当前倍率。"""

    t = ChatEngagementTracker()
    t.record_engagement("-100X", "a")
    t.record_engagement("-100X", "b")

    snap = t.snapshot()["-100X"]
    assert snap["events"] == 2
    assert snap["distinct_users"] == 2
    assert MIN_MULTIPLIER <= snap["multiplier"] <= MAX_MULTIPLIER
