"""出站自省与教训沉淀测试。

用真实翻车样本（\"你才sb\"、\"这也能看啊\"）验证闭环：
发言越界 → 被自省抓到 → 记入状态 → 回灌进 prompt。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.self_improvement import (  # noqa: E402
    ChatOutcome,
    SelfImprovementStore,
    inspect_own_message,
)


class _StubLogger:
    def info(self, *a: Any, **k: Any) -> None: ...
    def debug(self, *a: Any, **k: Any) -> None: ...
    def warning(self, *a: Any, **k: Any) -> None: ...
    def error(self, *a: Any, **k: Any) -> None: ...


# ---------------------------------------------------------------------------
# 检测层
# ---------------------------------------------------------------------------


def test_detects_real_aggressive_samples() -> None:
    """这些是线上真实发生过的攻击性发言，必须被抓到。"""

    for text in ["你才sb", "急了？", "谁是你妈"]:
        kind, hits = inspect_own_message(text)
        assert kind == "aggressive", f"{text!r} 未被识别为攻击性"
        assert hits


def test_detects_nsfw_followup() -> None:
    """顺着下流话题接话要被识别为\"被带偏\"。"""

    kind, hits = inspect_own_message("裸体有什么好看的")
    assert kind == "nsfw_followup"
    assert hits


def test_normal_speech_not_flagged() -> None:
    """正常聊天绝不能误报，否则会污染教训库。"""

    for text in [
        "早啊",
        "冒菜就是不用自己煮的麻辣烫吧",
        "不逗你了 你晚饭吃没",
        "哪里不行呀",
        "搬瓦工cn2 gia那个还行",
        "",
    ]:
        kind, _ = inspect_own_message(text)
        assert kind == "", f"{text!r} 被误判为 {kind}"


# ---------------------------------------------------------------------------
# 沉淀与回灌
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_violation_recorded_and_fed_back(tmp_path: Path) -> None:
    """越界发言要被记录，并出现在回灌 prompt 里 —— 这是闭环的关键。"""

    store = SelfImprovementStore(tmp_path, _StubLogger(), enabled=True)

    kind, hits = inspect_own_message("你才sb")
    await store.record_outcome(
        ChatOutcome(chat_id="-100123", text="你才sb", violation_kind=kind, violation_hits=hits)
    )

    block = store.build_prompt_block()
    assert "我犯过的错" in block
    assert "你才sb" in block
    assert "攻击性" in block


@pytest.mark.asyncio
async def test_nsfw_violation_gives_specific_guidance(tmp_path: Path) -> None:
    """被下流话题带偏时，回灌的提示要明确\"岔开或不接\"。"""

    store = SelfImprovementStore(tmp_path, _StubLogger(), enabled=True)

    kind, hits = inspect_own_message("裸体有啥好看")
    await store.record_outcome(
        ChatOutcome(chat_id="-100123", text="裸体有啥好看", violation_kind=kind, violation_hits=hits)
    )

    block = store.build_prompt_block()
    assert "带偏" in block or "岔开" in block


@pytest.mark.asyncio
async def test_clean_message_leaves_no_violation(tmp_path: Path) -> None:
    """正常发言不该往教训库里写东西。"""

    store = SelfImprovementStore(tmp_path, _StubLogger(), enabled=True)
    await store.record_outcome(ChatOutcome(chat_id="-100123", text="早啊", got_reply=True))

    block = store.build_prompt_block()
    assert "我犯过的错" not in block


@pytest.mark.asyncio
async def test_violation_samples_are_bounded(tmp_path: Path) -> None:
    """样本要有上界，长期运行不能无限膨胀。"""

    store = SelfImprovementStore(tmp_path, _StubLogger(), enabled=True)
    for i in range(80):
        await store.record_outcome(
            ChatOutcome(
                chat_id="-100123",
                text=f"你才sb{i}",
                violation_kind="aggressive",
                violation_hits=["sb"],
            )
        )

    samples = store._state.get("violation_samples", [])
    assert len(samples) <= 50


@pytest.mark.asyncio
async def test_violation_hits_not_leaked_to_prompt(tmp_path: Path) -> None:
    """命中词只用于本地排查，回灌 prompt 时不该把词表暴露出去。"""

    store = SelfImprovementStore(tmp_path, _StubLogger(), enabled=True)
    await store.record_outcome(
        ChatOutcome(
            chat_id="-100123",
            text="你才sb",
            violation_kind="aggressive",
            violation_hits=["sb", "你才"],
        )
    )

    block = store.build_prompt_block()
    # 原话可以出现（作为反面教材），但不该出现\"命中=\"这类内部字段
    assert "命中" not in block
    assert "hits" not in block
