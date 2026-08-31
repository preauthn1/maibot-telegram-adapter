"""全局发送速率上限测试。

2026-08-31 账号被 Telegram 反垃圾系统限制：
    04:02 SpamBot "no limits applied"
    16:42 SpamBot "your account was limited"
期间本地 transcript 记录出站 517 条，15 时单小时峰值 107 条。

根因是防护维度不全：此前所有检查都是"单条间隔"和"单群参与率"，
从没有人看单位时间的**全局总量**。间隔合规 + 多群并发 = 总量爆表。
真人一小时不会在群里发 107 条。

这里补上缺失的那一维：全局每小时 / 每分钟发送上限。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.send_budget import SendBudget  # noqa: E402


def test_hourly_cap_matches_human_range() -> None:
    """每小时上限须落在真人实测区间内。

    实测 563 个真人：单群峰值最高 80 条、前 10 名平均 68.9 条。
    定太低（如 30）会让账号反常沉默；定太高则失去防护意义。
    """

    budget = SendBudget()

    assert 45 <= budget.hourly_limit <= 75


def test_blocks_after_hourly_limit() -> None:
    """达到每小时上限后必须拒绝继续发送。"""

    budget = SendBudget(hourly_limit=5, minute_limit=99)
    for index in range(5):
        allowed, _ = budget.check(now=1000.0 + index)
        assert allowed is True
        budget.record(now=1000.0 + index)

    allowed, reason = budget.check(now=1006.0)

    assert allowed is False
    assert "小时" in reason


def test_minute_burst_blocked() -> None:
    """短时间连发也要拦——封禁前出现过单小时 107 条的爆发。"""

    budget = SendBudget(hourly_limit=99, minute_limit=3)
    for index in range(3):
        budget.record(now=2000.0 + index)

    allowed, reason = budget.check(now=2004.0)

    assert allowed is False
    assert "分钟" in reason


def test_window_slides() -> None:
    """超过窗口的旧记录要滑出，否则会永久锁死。"""

    budget = SendBudget(hourly_limit=2, minute_limit=99)
    budget.record(now=0.0)
    budget.record(now=1.0)

    assert budget.check(now=2.0)[0] is False
    # 一小时后旧记录滑出窗口
    assert budget.check(now=3700.0)[0] is True


def test_stats_reports_usage() -> None:
    """需要能读出当前用量，便于日志与巡检。"""

    budget = SendBudget(hourly_limit=10, minute_limit=5)
    budget.record(now=500.0)
    budget.record(now=501.0)

    stats = budget.stats(now=502.0)

    assert stats["last_hour"] == 2
    assert stats["last_minute"] == 2
    assert stats["hourly_limit"] == 10
