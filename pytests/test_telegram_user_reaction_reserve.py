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


def test_release_returns_hourly_quota_only() -> None:
    """回滚只还小时额度，冷却刻意不还。

    早先的实现连冷却一起还，导致「发送失败之后反而点得更频繁」，
    与限流意图相反。现在的语义是：额度还回去（不白占小时配额），
    但冷却继续计时（失败不等于可以立刻再来一次）。
    """

    # 冷却设为 0，单独观察小时额度这一项
    policy = ReactionPolicy(probability=1.0, chat_cooldown=0.0, hourly_limit=2)

    assert policy.reserve("chat-a", 1) is True
    assert policy.reserve("chat-a", 2) is True
    assert policy.reserve("chat-a", 3) is False, "小时额度已用尽"

    # 回滚一次，额度应当还回来
    policy.release("chat-a", 2)

    assert policy.reserve("chat-a", 4) is True, "回滚后小时额度没还回来"


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


def test_release_preserves_cooldown() -> None:
    """回滚不该清空冷却——否则一次失败就让下一条立刻放行。

    回归审计发现：release() 直接 pop 掉 _last_reaction_at，
    冷却完全绕过。而 plugin.py 的 finally 里几乎每条失败路径
    都会触发 release（pick_emoji 返回 None、消息已删、无权限、
    FloodWait），实战触发频率不低。
    """

    policy = _make_policy()

    # 占用成功但发送失败 → 回滚
    assert policy.reserve("chat-a", 1) is True
    policy.release("chat-a", 1)

    # 回滚只该还额度，不该把冷却也抹掉。
    # 若冷却被清空，下一条会立刻放行——表现为失败后反而更频繁。
    assert policy.reserve("chat-a", 2) is False, "回滚清空了冷却"


def test_release_does_not_affect_other_chats() -> None:
    """回滚 A 会话不该动到 B 会话的状态。

    原实现 pop 列表尾部，弹掉的可能是别的会话刚追加的时间戳。
    """

    policy = _make_policy()

    assert policy.reserve("chat-a", 1) is True
    assert policy.reserve("chat-b", 1) is True

    policy.release("chat-a", 1)

    # B 的冷却必须还在
    assert policy.reserve("chat-b", 2) is False, "回滚 A 影响了 B 的冷却"


def test_released_message_not_reacted_twice() -> None:
    """同一条消息回滚后不该被二次点表情。

    对同一条消息点两次是明显的脚本行为。_reacted 不该回滚。
    """

    policy = ReactionPolicy(probability=1.0, chat_cooldown=0.0, hourly_limit=100)

    assert policy.reserve("chat-a", 42) is True
    policy.release("chat-a", 42)

    assert policy.reserve("chat-a", 42) is False, "同一条消息被二次点表情"
