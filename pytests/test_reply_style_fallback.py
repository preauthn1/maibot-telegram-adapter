"""reply_style 未知值的降级测试。

线上实测：模型返回过 "简短回复"（近义词）和 "normal"（英文），
各 3 次。原实现用 `style_messages[key]` 直接下标取值，KeyError 会
冒泡到回复生成流程，直接吃掉一次发言机会（实测 6 次崩溃、
1 次生成失败）。

风格提示只是锦上添花，未知值降级为空串即可。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.chat.replyer.maisaka_generator_base import (  # noqa: E402
    BaseMaisakaReplyGenerator,
)

_build = BaseMaisakaReplyGenerator._build_requested_reply_style_message


def test_known_styles_still_work() -> None:
    """登记过的三个值行为不变。"""

    assert "简短" in _build("简短表达")
    assert _build("正常回复") == ""
    assert "详细" in _build("长回复")


def test_unknown_chinese_style_degrades() -> None:
    """近义词 "简短回复" 不应抛异常。"""

    assert _build("简短回复") == ""


def test_unknown_english_style_degrades() -> None:
    """英文 "normal" 不应抛异常。"""

    assert _build("normal") == ""


def test_empty_style_returns_empty() -> None:
    """空值与空白照旧返回空串。"""

    assert _build("") == ""
    assert _build("   ") == ""


def test_arbitrary_garbage_degrades() -> None:
    """任意脏值都必须降级，不能让一次发言因此丢掉。"""

    for value in ("???", "长回复长回复", "SHORT", "简短", "1"):
        assert _build(value) == ""
