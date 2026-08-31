"""触发分级测试。

移植自 AEsirClaw 的 TriggerManager，解决我们现有的缺陷：
``small_chat`` 只有单一发言间隔，不区分「被 @ 必须答」和
「随便接话」两种完全不同的场景。

真人的行为是分级的：
- 被点名问到 → 立刻答，不受"我刚说过话"影响
- 群里闲聊   → 有话说才插一句，且要看自己是不是刚说过

对参考实现的三处修正：
1. 参考实现在 ``check()`` 里调 ``record_response()``——「打算回复」
   就记冷却。但决策后还可能被参与率、内容过滤拦掉，实际没发言
   却已占用冷却，导致该说话时反而沉默。改为发送成功后由调用方记账。
2. 参考实现末尾有不可达代码（``return`` 之后还有 ``return``）。
3. 参考实现私聊冷却 1 秒——对真人号太快，1 秒连答是机器特征。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.trigger import (  # noqa: E402
    TriggerLevel,
    TriggerManager,
)


def test_private_chat_is_forced() -> None:
    """私聊必须回——有人专门私聊你，不回很反常。"""

    manager = TriggerManager()

    result = manager.evaluate("user-1", "在吗", is_private=True, is_directed=False)

    assert result.should_respond is True
    assert result.level is TriggerLevel.FORCED


def test_mention_is_forced() -> None:
    """被 @ 必须回，且不受普通冷却限制。"""

    manager = TriggerManager()
    manager.record_response("chat-a", now=1000.0)

    result = manager.evaluate(
        "chat-a", "帮我看下", is_private=False, is_directed=True, now=1001.0
    )

    assert result.should_respond is True
    assert result.level is TriggerLevel.FORCED


def test_keyword_hit_bypasses_group_cooldown() -> None:
    """命中关注关键词时可以插话，但仍受较短的关键词冷却约束。"""

    manager = TriggerManager(keywords=("xray", "reality"))

    result = manager.evaluate(
        "chat-a", "这个 xray 配置有问题", is_private=False, is_directed=False
    )

    assert result.should_respond is True
    assert result.level is TriggerLevel.KEYWORD


def test_casual_chat_respects_cooldown() -> None:
    """闲聊在冷却期内不应发言——刚说过话就接着说是刷屏特征。"""

    manager = TriggerManager(group_cooldown=60.0)
    manager.record_response("chat-a", now=1000.0)

    result = manager.evaluate(
        "chat-a", "哈哈", is_private=False, is_directed=False, now=1010.0
    )

    assert result.should_respond is False
    assert result.level is TriggerLevel.NONE
    assert "冷却" in result.reason


def test_casual_chat_allowed_after_cooldown() -> None:
    """冷却过后可以正常参与闲聊。"""

    manager = TriggerManager(group_cooldown=60.0)
    manager.record_response("chat-a", now=1000.0)

    result = manager.evaluate(
        "chat-a", "哈哈", is_private=False, is_directed=False, now=1100.0
    )

    assert result.should_respond is True
    assert result.level is TriggerLevel.CASUAL


def test_check_does_not_consume_cooldown() -> None:
    """evaluate 只做判断，不得自行记账。

    参考实现在 check() 里就调 record_response()，导致「打算回复」
    即占用冷却；但决策后还可能被参与率、内容过滤拦掉，
    实际没发言却已消耗冷却，表现为该说话时反而沉默。
    """

    manager = TriggerManager(group_cooldown=60.0)

    first = manager.evaluate(
        "chat-a", "随便说说", is_private=False, is_directed=False, now=1000.0
    )
    second = manager.evaluate(
        "chat-a", "再说一句", is_private=False, is_directed=False, now=1001.0
    )

    assert first.should_respond is True
    assert second.should_respond is True, "evaluate 不应自行消耗冷却"


def test_private_cooldown_not_instant() -> None:
    """私聊冷却不能是 1 秒——秒回连答是机器特征。"""

    manager = TriggerManager()

    assert manager.private_cooldown >= 3.0


def test_independent_cooldown_per_chat() -> None:
    """各会话冷却独立计算。"""

    manager = TriggerManager(group_cooldown=60.0)
    manager.record_response("chat-a", now=1000.0)

    result = manager.evaluate(
        "chat-b", "你们在聊什么", is_private=False, is_directed=False, now=1005.0
    )

    assert result.should_respond is True


def test_stats_reports_cooldown_state() -> None:
    """需要能读出剩余冷却，便于日志与巡检。"""

    manager = TriggerManager(group_cooldown=60.0)
    manager.record_response("chat-a", now=1000.0)

    remaining = manager.cooldown_remaining("chat-a", now=1020.0)

    assert 39.0 <= remaining <= 41.0
