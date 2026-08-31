"""注意力焦点测试：限制同时活跃的群数，而非单纯限制总量。

实测数据（2026-08-31，样本 4 群 / 563 个真人发言者）：
- 真人单群小时峰值最高 80 条，前 10 名平均 68.9 条
- 峰值 ≥107 条的真人：0/563
- **单小时跨 ≥3 个群发言的真人：0/1128 条记录**
- 前 15 名高发言者中 14 个是单群，1 个是 2 群

结论修正：我方封禁前 15 时发 107 条，量级与真人水群者(80)接近，
不是主因。真正扎眼的是那 107 条**分散在 12 个群**——真人注意力
是独占的，不可能同一小时在十几个互不相关的群里活跃。

因此限制维度应是「同时在场群数」+「注意力焦点」，
而不是把总量掐到远低于真人的水平。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.attention_focus import AttentionFocus  # noqa: E402


def test_concurrent_chat_limit_matches_humans() -> None:
    """并发群数上限须落在真人实测范围内（观测到最多 2 群）。"""

    focus = AttentionFocus()

    assert focus.max_concurrent_chats <= 3


def test_first_chats_allowed() -> None:
    """未达上限前，各群都应放行。"""

    focus = AttentionFocus(max_concurrent_chats=2)

    allowed, _ = focus.check("chat-a", now=1000.0)
    assert allowed is True
    focus.record("chat-a", now=1000.0)

    allowed, _ = focus.check("chat-b", now=1010.0)
    assert allowed is True
    focus.record("chat-b", now=1010.0)


def test_third_chat_blocked_while_focused() -> None:
    """已在 2 个群活跃时，第 3 个群必须被挡——这是真人从不出现的模式。"""

    focus = AttentionFocus(max_concurrent_chats=2)
    focus.record("chat-a", now=1000.0)
    focus.record("chat-b", now=1010.0)

    allowed, reason = focus.check("chat-c", now=1020.0)

    assert allowed is False
    assert "注意力" in reason


def test_active_chat_still_allowed_when_at_limit() -> None:
    """已在焦点内的群不受影响——真人会持续在同一个群聊。"""

    focus = AttentionFocus(max_concurrent_chats=2)
    focus.record("chat-a", now=1000.0)
    focus.record("chat-b", now=1010.0)

    allowed, _ = focus.check("chat-a", now=1020.0)

    assert allowed is True


def test_focus_expires_and_rotates() -> None:
    """旧焦点过期后应释放名额，否则账号会永久锁死在最初两个群。"""

    focus = AttentionFocus(max_concurrent_chats=2, focus_window_seconds=600.0)
    focus.record("chat-a", now=0.0)
    focus.record("chat-b", now=10.0)

    assert focus.check("chat-c", now=100.0)[0] is False
    # 窗口过后注意力可以转移到别的群
    assert focus.check("chat-c", now=700.0)[0] is True


def test_stats_exposes_current_focus() -> None:
    """需要能读出当前焦点群，便于日志与巡检。"""

    focus = AttentionFocus(max_concurrent_chats=2)
    focus.record("chat-a", now=500.0)

    stats = focus.stats(now=501.0)

    assert stats["active_chats"] == 1
    assert stats["max_concurrent_chats"] == 2
