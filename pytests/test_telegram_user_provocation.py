"""针对性挑衅识别与回应测试。

两条硬性要求：
1. **只在被直接针对时触发**。群里骂别人、或聊天里出现脏字，
   都不该让我们跳出来——误伤一个无辜的人代价远大于放过一次挑衅。
2. **回应绝不带脏字**。带了就是同一水平的对骂，既可能被封号，
   对方也不会难受。
"""

from __future__ import annotations

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.provocation import (  # noqa: E402
    _COMEBACKS,
    _INSULT_WORDS,
    ProvocationResponder,
    detect_provocation,
)


def test_real_provocation_samples_detected() -> None:
    """线上真实挑衅样本必须命中。"""

    samples = [
        "@testuser 傻逼？",
        "骂你妈逼啊",
        "md你谁啊",
        "𝘎𝘳𝘢𝘺𝘴𝘰𝘯 滚出去",
        "你算老几",
    ]
    for text in samples:
        hit, _ = detect_provocation(text, is_directed=True)
        assert hit, f"{text!r} 未被识别为挑衅"


def test_not_directed_never_triggers() -> None:
    """⚠️ 关键：没 @ 我们就一律不触发——群里骂别人不关我们的事。"""

    for text in ["傻逼玩意", "这什么破东西 滚吧", "你妈的这游戏"]:
        hit, _ = detect_provocation(text, is_directed=False)
        assert not hit, f"{text!r} 在未针对我们时不该触发"


def test_normal_directed_message_not_flagged() -> None:
    """正常 @ 我们说话不该被当成挑衅。"""

    for text in [
        "@testuser 在吗",
        "@testuser 这个怎么弄",
        "@testuser 谢谢啊",
        "@testuser 你那个节点还能用吗",
    ]:
        hit, _ = detect_provocation(text, is_directed=True)
        assert not hit, f"{text!r} 被误判为挑衅"


def test_empty_text_safe() -> None:
    """空消息（贴纸、图片）不该触发。"""

    assert not detect_provocation("", is_directed=True)[0]
    assert not detect_provocation("   ", is_directed=True)[0]


def test_comebacks_contain_no_profanity() -> None:
    """⚠️ 硬性要求：回应库里绝不能有脏字。"""

    for line in _COMEBACKS:
        low = line.lower()
        for bad in _INSULT_WORDS:
            assert bad not in low, f"回应 {line!r} 含脏字 {bad!r}"


def test_comebacks_are_varied() -> None:
    """话术要有多条，同一句反复出现会被认出是模板。"""

    assert len(set(_COMEBACKS)) >= 6


def test_responds_once_then_cools_down() -> None:
    """回一次后进入冷却，避免变成即时对喷。"""

    r = ProvocationResponder(cooldown=300.0)

    first = r.build_response("-100X", "troll", monotonic_now=0.0)
    assert first is not None

    # 冷却期内不再回
    assert r.build_response("-100X", "troll", monotonic_now=100.0) is None

    # 冷却结束后可以再回一次
    assert r.build_response("-100X", "troll", monotonic_now=400.0) is not None


def test_cooldown_is_per_user() -> None:
    """对一个人冷却不影响回应另一个人。"""

    r = ProvocationResponder(cooldown=300.0)
    r.build_response("-100X", "troll_a", monotonic_now=0.0)

    assert r.build_response("-100X", "troll_b", monotonic_now=1.0) is not None


def test_cooldown_is_per_chat() -> None:
    """同一个人在不同群分别计冷却。"""

    r = ProvocationResponder(cooldown=300.0)
    r.build_response("-100A", "troll", monotonic_now=0.0)

    assert r.build_response("-100B", "troll", monotonic_now=1.0) is not None


def test_response_comes_from_library() -> None:
    """回应必须来自预置话术库，不能是模型现场生成的——
    被激怒时让 LLM 自由发挥，很容易说出真正难听的话。"""

    r = ProvocationResponder()
    text = r.build_response("-100X", "troll", monotonic_now=0.0)
    assert text in _COMEBACKS


def test_never_repeats_same_line_consecutively() -> None:
    """连着对同一个人说同一句话会露出模板痕迹。"""

    r = ProvocationResponder(cooldown=0.0)
    previous = None
    for i in range(20):
        text = r.build_response("-100X", "troll", monotonic_now=float(i))
        assert text != previous, f"第 {i} 次重复了上一句: {text!r}"
        previous = text
