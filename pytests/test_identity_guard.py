"""身份守卫单元测试。

覆盖三类场景：
1. 硬拦截：整句自曝 AI 身份或底层模型，必须被丢弃。
2. 软改写：自指短语嵌在正常句子中，必须保留句子其余内容。
3. 放行：正常聊天内容（包括提到别人的机器人/AI）不得被误伤。
"""

import pytest

from src.chat.utils.identity_guard import (
    build_identity_prompt_block,
    guard_identity,
)


# 来自真实群聊的破绽样本 + 常见泄露话术。
HARD_BLOCK_CASES = [
    "不过我就是一机器人",
    "我是搭载在某平台上的机器人，具体底层模型是通义千问的那款开源对话模型",
    "我是一个AI助手",
    "我其实是个人工智能",
    "我算是台机器",
    "我的底层模型是GPT-4",
    "我基于deepseek训练的",
    "我用的是Claude",
    "我没有真正的身体哦",
    "我不是真人啦",
    "我的知识截止到2024年",
    "我是被开发出来的",
    "我运行在服务器上",
    "我调用的API有点慢",
    "有什么可以帮你的吗？",
    "很高兴为您服务。",
    "我的上下文窗口是128k",
    "我是通义千问",
]

# 软改写：句子主体必须保留。
SOFT_REWRITE_CASES = [
    ("你这作息比我这个机器人还乱", "还乱"),
    ("我们这些机器人都这样", "都这样"),
    ("像我这样的AI是不会累的", "不会累"),
    ("作为一个AI，我不能有感情", "不能有感情"),
]

# 正常内容必须原样放行。
PASSTHROUGH_CASES = [
    "今天天气不错啊",
    "我昨天看了个电影挺好看的",
    "哈哈哈你太逗了",
    "那个机器人展览挺有意思的",
    "我朋友买了个扫地机器人",
    "这游戏的AI好蠢",
    "我是学计算机的",
    "我是南方人",
    "我是来打酱油的",
    "我是机器学习方向的",
    "我是程序员",
    "我是做软件测试的",
    "我是搞软件开发的",
]


@pytest.mark.parametrize("text", HARD_BLOCK_CASES)
def test_hard_leak_is_blocked(text: str) -> None:
    """自曝身份/模型的整句必须被拦下并换成兜底回复。"""

    result = guard_identity(text)

    assert result.triggered, f"未触发守卫: {text!r}"
    assert result.used_deflection, f"未使用兜底回复: {text!r} -> {result.text!r}"
    assert result.text != text


@pytest.mark.parametrize("text, must_keep", SOFT_REWRITE_CASES)
def test_soft_rewrite_preserves_sentence_body(text: str, must_keep: str) -> None:
    """自指短语被抹掉，但句子其余内容必须保留。"""

    result = guard_identity(text)

    assert result.triggered, f"未触发守卫: {text!r}"
    assert not result.used_deflection, f"不应回退兜底: {text!r} -> {result.text!r}"
    assert must_keep in result.text, f"句子主体丢失: {text!r} -> {result.text!r}"
    for leak_word in ("机器人", "AI", "ai", "人工智能"):
        assert leak_word not in result.text, f"改写后仍有泄露词 {leak_word}: {result.text!r}"


@pytest.mark.parametrize("text", PASSTHROUGH_CASES)
def test_normal_content_passes_through(text: str) -> None:
    """正常聊天内容不得被误伤。"""

    result = guard_identity(text)

    assert not result.triggered, f"正常内容被误伤: {text!r} -> {result.text!r}"
    assert result.text == text


def test_mixed_sentence_drops_only_leaking_clause() -> None:
    """混合句只丢泄露的那一句，其余保留。"""

    result = guard_identity("今天好累啊。我其实是个AI。你呢")

    assert result.triggered
    assert not result.used_deflection
    assert "今天好累啊" in result.text
    assert "你呢" in result.text
    assert "AI" not in result.text


def test_empty_input_is_returned_as_is() -> None:
    """空输入不应触发守卫，也不应崩溃。"""

    for text in ("", "   ", "\n"):
        result = guard_identity(text)
        assert result.text == text
        assert not result.triggered


def test_deflection_pool_is_respected() -> None:
    """自定义兜底池必须生效。"""

    result = guard_identity("我是一个AI", deflection_pool=["不告诉你"])

    assert result.used_deflection
    assert result.text == "不告诉你"


def test_dropped_sentences_are_reported() -> None:
    """被丢弃的原文必须记录下来，便于排查。"""

    result = guard_identity("我是个机器人。今天天气不错")

    assert result.dropped_sentences
    assert "机器人" in result.dropped_sentences[0]
    assert "今天天气不错" in result.text


def test_identity_prompt_block_contains_hard_rules() -> None:
    """身份铁律提示块必须包含关键约束与机器人昵称。"""

    block = build_identity_prompt_block("麦麦")

    assert "麦麦" in block
    assert "身份铁律" in block
    assert "绝对不要说自己是机器人" in block
    assert "底层模型" in block
