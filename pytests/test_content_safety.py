"""入站内容安全过滤测试。

重点在**误判**：过度拦截会让账号在正常对话里突然沉默，
比偶尔漏判更可疑，也更容易被识别为自动化。
"""

from __future__ import annotations

from pathlib import Path

import sys

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "plugins"
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from telegram_user_adapter.content_safety import detect_nsfw  # noqa: E402


@pytest.mark.parametrize(
    "text",
    [
        "有约炮的吗",
        "发个裸照来看看",
        "这个av女优叫什么",
        "想看黄片",
        "他被强奸了",
        "招嫖广告一堆",
        "自慰算不算",
        "porn hub 上不去",
        "send me nudes",
        "this is nsfw content",
        "watch hentai online",
        "looking for escort service",
    ],
)
def test_explicit_content_is_detected(text: str) -> None:
    """明确的露骨内容必须被识别。"""

    hit, keywords = detect_nsfw(text)

    assert hit, f"未识别: {text!r}"
    assert keywords, "命中时应返回关键词用于日志排查"


@pytest.mark.parametrize(
    "text",
    [
        "今天天气不错",
        "这个操作有点骚啊",
        "我胸口有点疼",
        "腿麻了",
        "比赛进入高潮迭起的阶段",
        "剧情到高潮了",
        "调教一下模型参数",
        "把代码调教好",
        "我在做数据分析",
        "这个 API 怎么用",
        "他是个成年人了",
        "性能优化怎么做",
        "男性和女性用户比例",
        "这部电影很色彩斑斓",
        "cpu 占用率高",
    ],
)
def test_normal_conversation_is_not_flagged(text: str) -> None:
    """正常对话绝不能被误判。

    误判会让账号在普通聊天里突然不回话，这比偶尔漏判更容易暴露。
    """

    hit, keywords = detect_nsfw(text)

    assert not hit, f"误判为 NSFW: {text!r} 命中={keywords}"


def test_empty_input_is_safe() -> None:
    """空输入不应命中，也不应抛异常。"""

    assert detect_nsfw("") == (False, [])
    assert detect_nsfw(None) == (False, [])
    assert detect_nsfw("   ") == (False, [])


def test_ambiguous_word_in_explicit_context_still_flagged() -> None:
    """歧义词的白名单不应把真正的露骨内容也放过。"""

    hit, _ = detect_nsfw("聊点色情的，做爱那种")

    assert hit


def test_benign_context_does_not_shield_explicit_terms() -> None:
    """同一段话里既有正常语境又有明确露骨词时，仍必须拦截。

    否则只要在露骨内容里掺一句"剧情高潮"就能绕过过滤。
    """

    hit, keywords = detect_nsfw("剧情高潮的时候他们做爱了")

    assert hit, "正常语境不应掩护明确露骨词"
    assert "做爱" in keywords
    assert "高潮" not in keywords, "歧义词在正常语境下不应计入命中"


def test_keywords_are_deduplicated() -> None:
    """重复命中同一个词时应去重，避免日志噪音。"""

    _, keywords = detect_nsfw("裸照 裸照 裸照")

    assert keywords.count("裸照") == 1


def test_detection_is_case_insensitive() -> None:
    """英文关键词应忽略大小写。"""

    assert detect_nsfw("NSFW")[0]
    assert detect_nsfw("Porn")[0]
    assert detect_nsfw("HENTAI")[0]


def test_minor_related_content_is_flagged() -> None:
    """涉未成年的露骨内容必须拦截。"""

    assert detect_nsfw("恋童")[0]
    assert detect_nsfw("child porn")[0]
