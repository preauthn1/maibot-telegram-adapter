"""主动表情回应的节流策略测试。

点表情本身很轻，但**频率**决定了会不会被判定为脚本。
这里重点验证概率、冷却、每小时上限、去重四道闸门都真的生效。
"""

from __future__ import annotations

from pathlib import Path

import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.reaction_policy import (  # noqa: E402
    SAFE_REACTIONS,
    ReactionPolicy,
    resolve_allowed_reactions,
)


def _policy(**kwargs) -> ReactionPolicy:
    """构造一个便于测试的策略实例。"""

    defaults = dict(probability=1.0, chat_cooldown=0.0, hourly_limit=1000)
    defaults.update(kwargs)
    return ReactionPolicy(**defaults)


def test_probability_zero_never_reacts() -> None:
    """概率为 0 时必须完全不点表情。"""

    policy = _policy(probability=0.0)
    assert not any(policy.should_react("-100123", i) for i in range(200))


def test_same_message_never_reacted_twice() -> None:
    """同一条消息重复点表情是明显的脚本行为。"""

    policy = _policy()
    assert policy.should_react("-100123", 5)
    policy.mark_reacted("-100123", 5)
    assert not policy.should_react("-100123", 5)


def test_chat_cooldown_blocks_rapid_reactions() -> None:
    """同一会话短时间内连点必须被冷却挡住。"""

    policy = _policy(chat_cooldown=600.0)
    assert policy.should_react("-100123", 1)
    policy.mark_reacted("-100123", 1)
    # 冷却期内，另一条消息也不能点
    assert not policy.should_react("-100123", 2)


def test_cooldown_is_per_chat() -> None:
    """冷却按会话独立计算，不该殃及其他群。"""

    policy = _policy(chat_cooldown=600.0)
    policy.mark_reacted("-100111", 1)
    # 另一个群不受影响
    assert policy.should_react("-100222", 1)


def test_hourly_limit_enforced() -> None:
    """每小时上限是防封号的硬闸门。"""

    policy = _policy(hourly_limit=3)
    for i in range(3):
        assert policy.should_react(f"-100{i}", i)
        policy.mark_reacted(f"-100{i}", i)
    # 第 4 次必须被拦
    assert not policy.should_react("-100999", 999)


def test_disabled_chat_is_skipped() -> None:
    """被标记为不支持表情的会话直接跳过。"""

    policy = _policy()
    policy.mark_chat_disabled("-100123")
    assert not policy.should_react("-100123", 1)


def test_keyword_emoji_selection() -> None:
    """表情要贴合语境，而不是随机乱点。"""

    policy = _policy()
    assert policy.pick_emoji("-100123", "哈哈哈笑死我了") == "😁"
    assert policy.pick_emoji("-100123", "谢谢大佬") == "❤"
    assert policy.pick_emoji("-100123", "这也太牛了吧") == "🔥"
    assert policy.pick_emoji("-100123", "恭喜上岸") == "🎉"
    assert policy.pick_emoji("-100123", "这什么鬼 太离谱了") == "🤯"


def test_blacklisted_emoji_not_picked() -> None:
    """被拒绝过的表情不能再选，否则会一直撞同一个错误。"""

    policy = _policy()
    policy.blacklist_emoji("-100123", "😁")
    for _ in range(50):
        assert policy.pick_emoji("-100123", "哈哈哈") != "😁"


def test_allowed_set_restricts_choice() -> None:
    """群管理员限制了表情范围时必须遵守。"""

    policy = _policy()
    allowed = {"👍"}
    for _ in range(50):
        assert policy.pick_emoji("-100123", "哈哈哈笑死", allowed) == "👍"


def test_pick_emoji_returns_none_when_nothing_usable() -> None:
    """无可用表情时返回 None，而不是硬发一个会被拒的表情。"""

    policy = _policy()
    assert policy.pick_emoji("-100123", "随便", set()) is None


def test_resolve_allowed_reactions_none_means_unrestricted() -> None:
    """字段缺省表示管理员没限制，不能误当成\"禁用\"。"""

    assert resolve_allowed_reactions(None) is None


def test_resolve_allowed_reactions_variants() -> None:
    """三种 ChatReactions 形态都要解析正确。"""

    from telethon.tl import types

    # 全部允许
    assert resolve_allowed_reactions(types.ChatReactionsAll()) is None

    # 明确禁用 -> 空集合
    assert resolve_allowed_reactions(types.ChatReactionsNone()) == set()

    # 白名单
    some = types.ChatReactionsSome(
        reactions=[types.ReactionEmoji(emoticon="👍"), types.ReactionEmoji(emoticon="❤")]
    )
    assert resolve_allowed_reactions(some) == {"👍", "❤"}


def test_safe_reactions_are_non_empty() -> None:
    """安全表情池不能为空，否则功能形同虚设。"""

    assert len(SAFE_REACTIONS) >= 5
