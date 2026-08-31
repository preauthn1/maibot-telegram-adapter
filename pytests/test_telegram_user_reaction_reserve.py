"""表情节流的并发安全测试。

审计发现的 P0：``should_react`` 是纯判定、不推进状态，而冷却与
限流只在 ``mark_reacted`` 里更新——后者在 1.5-6.0 秒随机延迟之后
才被调用。这段延迟就是 check-then-act 窗口。

实测（probability=1.0、chat_cooldown=300s、hourly_limit=5，
灌入 20 条消息）：**20 条全部通过，20 个表情全部发出**，应为 1 条。
表现为几秒内对一串消息批量点表情，正是本模块要防的脚本行为。

修复：新增 ``reserve()``，判定与记账在同一同步临界区内完成；
配套 ``release()`` 供发送失败时回滚。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.reaction_policy import ReactionPolicy  # noqa: E402


def _make_policy() -> ReactionPolicy:
    """构造一个必定想点表情、但冷却很长的策略。"""

    return ReactionPolicy(
        probability=1.0,
        chat_cooldown=300.0,
        hourly_limit=5,
    )


def test_reserve_blocks_burst() -> None:
    """突发消息只应通过一条——这是修复的核心。

    原实现 20 条全部通过，因为记账在几秒后才发生。
    """

    policy = _make_policy()

    passed = [
        message_id
        for message_id in range(20)
        if policy.reserve("chat-a", message_id)
    ]

    assert len(passed) == 1, (
        f"突发 20 条消息放行了 {len(passed)} 条，冷却未生效"
    )


def test_should_react_alone_does_not_throttle() -> None:
    """记录原缺陷：单用 should_react 无法节流。

    这条测试锁定"为什么必须用 reserve"，防止有人改回去。
    """

    policy = _make_policy()

    passed = [
        message_id
        for message_id in range(20)
        if policy.should_react("chat-a", message_id)
    ]

    assert len(passed) == 20, (
        "should_react 本就只做判定不记账；若这里变了，"
        "说明语义被改动，plugin 的 reserve 用法需要复查"
    )


def test_release_returns_quota() -> None:
    """发送失败时归还额度，下一条应能重新通过。"""

    policy = _make_policy()

    assert policy.reserve("chat-a", 1) is True
    policy.release("chat-a", 1)

    assert policy.reserve("chat-a", 2) is True, "回滚后额度没还回来"


def test_release_without_reserve_is_safe() -> None:
    """未预占就回滚不应报错，也不该凭空放宽额度。"""

    policy = _make_policy()

    policy.release("chat-a", 999)

    assert policy.reserve("chat-a", 1) is True


def test_hourly_limit_still_enforced() -> None:
    """小时上限仍要生效——冷却过去后也不能无限点。"""

    policy = ReactionPolicy(
        probability=1.0,
        chat_cooldown=0.0,
        hourly_limit=3,
    )

    passed = [
        message_id
        for message_id in range(10)
        if policy.reserve("chat-a", message_id)
    ]

    assert len(passed) == 3, f"小时上限 3，实际放行 {len(passed)}"


def test_separate_chats_have_own_cooldown() -> None:
    """不同会话的冷却互相独立。"""

    policy = _make_policy()

    assert policy.reserve("chat-a", 1) is True
    assert policy.reserve("chat-b", 1) is True
    assert policy.reserve("chat-a", 2) is False
