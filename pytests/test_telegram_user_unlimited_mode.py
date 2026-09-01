"""极端实验模式的双向验证。

必须双向测：开关打开时限制真的解除、关闭时限制真的还在。
只测一个方向的话，"开关没接上"和"开关生效了"看起来一样
（都是测试通过）。

⚠️ 同时锁定身份类防护不受开关影响——那是本实验的前提：
上次封号走的是"被人看出不是真人 → 举报 → 人工确认"链路，
与发言频率无关。如果开关顺手把身份防护也关了，
实验结果就无法归因。
"""

from pathlib import Path

import pytest

from plugins.telegram_user_adapter import unlimited_mode
from plugins.telegram_user_adapter.attention_focus import AttentionFocus
from plugins.telegram_user_adapter.send_budget import SendBudget
from plugins.telegram_user_adapter.small_chat import SmallChatModerator

_ENV_KEY = "TG_UNLIMITED_MODE"


@pytest.fixture
def unlimited(monkeypatch):
    """打开极端实验模式。"""

    monkeypatch.setenv(_ENV_KEY, "1")
    return True


@pytest.fixture
def normal(monkeypatch):
    """确保处于正常模式（防止外部环境变量污染测试）。"""

    monkeypatch.delenv(_ENV_KEY, raising=False)
    return True


def test_flag_reads_env(monkeypatch) -> None:
    """开关只认明确的真值，避免误开。"""

    for value in ("1", "true", "yes", "on"):
        monkeypatch.setenv(_ENV_KEY, value)
        assert unlimited_mode.is_unlimited() is True

    for value in ("", "0", "false", "no", "off", "maybe"):
        monkeypatch.setenv(_ENV_KEY, value)
        assert unlimited_mode.is_unlimited() is False


def test_budget_blocks_in_normal_mode(normal) -> None:
    """正常模式：分钟限额必须仍然拦截。"""

    budget = SendBudget(hourly_limit=100, minute_limit=3)
    now = 1000.0
    for _ in range(3):
        budget.record(now=now)

    allowed, reason = budget.check(now=now)

    assert allowed is False
    assert "每分钟" in reason


def test_budget_unlimited(unlimited) -> None:
    """实验模式：远超限额仍放行，但记账不停。"""

    budget = SendBudget(hourly_limit=100, minute_limit=3)
    now = 1000.0
    for _ in range(50):
        budget.record(now=now)

    allowed, reason = budget.check(now=now)

    assert allowed is True
    assert reason == ""
    # 记账仍在进行——这是事后统计"会被挡掉多少"的依据
    last_hour, last_minute = budget._counts(now)
    assert last_minute == 50


def test_attention_blocks_in_normal_mode(normal) -> None:
    """正常模式：并发会话数上限必须仍然拦截。"""

    focus = AttentionFocus(max_concurrent_chats=2)
    now = 500.0
    for index in range(2):
        focus.record(f"-100900000000{index}", now=now)

    allowed, reason = focus.check("-1009000000009", now=now)

    assert allowed is False
    assert "注意力" in reason


def test_attention_unlimited(unlimited) -> None:
    """实验模式：并发会话数不再受限。"""

    focus = AttentionFocus(max_concurrent_chats=2)
    now = 500.0
    for index in range(8):
        focus.record(f"-100900000000{index}", now=now)

    allowed, reason = focus.check("-1009000000099", now=now)

    assert allowed is True
    assert reason == ""


def test_small_chat_suppresses_in_normal_mode(normal) -> None:
    """正常模式：最小发言间隔必须仍然拦截。"""

    moderator = SmallChatModerator(min_gap=30.0)
    chat = "-1009000000001"
    moderator.record_outbound(chat, "随便说句话", now=1000.0)

    suppress, reason = moderator.should_suppress(
        chat, member_count=4, now=1005.0
    )

    assert suppress is True
    assert reason


def test_small_chat_unlimited(unlimited) -> None:
    """实验模式：间隔与参与率均不再压制。"""

    moderator = SmallChatModerator(min_gap=30.0)
    chat = "-1009000000001"
    for offset in range(10):
        moderator.record_outbound(chat, f"第{offset}条", now=1000.0 + offset)

    suppress, reason = moderator.should_suppress(
        chat, member_count=4, now=1010.0
    )

    assert suppress is False
    assert reason == ""


def test_identity_guards_not_gated_by_unlimited() -> None:
    """身份类防护不得被本开关影响。

    这是实验能否归因的前提。若某天有人顺手把 is_unlimited 加到
    污染检测或发言前自检里，本测试立刻失败。
    """

    plugin_dir = Path("plugins/telegram_user_adapter")
    identity_modules = [
        plugin_dir / "pre_send_review.py",
        plugin_dir / "self_improvement.py",
        plugin_dir / "spam_filter.py",
    ]

    for path in identity_modules:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        assert "is_unlimited" not in source, (
            f"{path.name} 引用了频率开关——身份防护必须无条件生效"
        )
