"""发言前自检测试（借鉴 Hermes 的技能加载 + 反思机制）。

现有 self_improvement 是「事后学习」：发出去之后看有没有被接话、
有没有被质疑，再把教训写进 SKILL.md。这是必要的，但太晚了——
账号 2026-08-31 因用户举报被封，等到「事后」已经来不及。

Hermes 的做法是**决策前先加载相关知识**：
- 技能索引里挑出与当前任务相关的条目，读进来再动手
- 高风险操作先自检再执行，不是先执行再补救

这里把这个思路落成「发言前自检」：把已积累的教训（SKILL.md 里
记录的失败模式）在**发言前**匹配一遍，命中就拦下来。

关键区别：
- self_improvement.record_outcome  → 事后，从后果学习
- pre_send_review.review           → 事前，用已学到的拦住重犯
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.pre_send_review import (  # noqa: E402
    LessonStore,
    ReviewVerdict,
    review_draft,
)


def test_clean_text_passes() -> None:
    """没有命中任何教训的正常发言应放行。"""

    store = LessonStore(patterns=("秒回",))

    verdict = review_draft("这个我也遇到过，重启就好了", store=store)

    assert verdict.allowed is True


def test_known_failure_pattern_blocked() -> None:
    """命中已记录的失败模式必须拦下。"""

    store = LessonStore(patterns=("作为一个 ai", "我是人工智能"))

    verdict = review_draft("作为一个 AI，我认为这样不太好", store=store)

    assert verdict.allowed is False
    assert "作为一个 ai" in verdict.reason.lower()


def test_pattern_match_is_case_insensitive() -> None:
    """大小写不应绕过检查。"""

    store = LessonStore(patterns=("as an ai",))

    verdict = review_draft("As An AI language model, I think...", store=store)

    assert verdict.allowed is False


def test_empty_store_allows_everything() -> None:
    """还没积累教训时不应误拦。"""

    store = LessonStore(patterns=())

    assert review_draft("随便说点什么", store=store).allowed is True


def test_lessons_loaded_from_markdown() -> None:
    """教训从 Markdown 加载——沿用画像卡的人可读格式。"""

    text = """# 聊天教训

## 禁用表达（发言前自检）

- `作为一个 AI`：直接暴露身份
- `根据我的训练数据`：同上
- 普通说明文字，不是模式

## 其他记录

随便写的正文，不该被当成模式。
"""

    store = LessonStore.from_markdown(text)

    assert "作为一个 ai" in store.patterns
    assert "根据我的训练数据" in store.patterns
    # 没有反引号包裹的行不算模式
    assert not any("普通说明文字" in p for p in store.patterns)


def test_verdict_carries_matched_pattern() -> None:
    """拦截时要能说出命中了哪条教训，便于排查与人工复核。"""

    store = LessonStore(patterns=("我没有感情",))

    verdict = review_draft("抱歉，我没有感情", store=store)

    assert isinstance(verdict, ReviewVerdict)
    assert verdict.matched == "我没有感情"


def test_only_designated_section_parsed() -> None:
    """只解析「禁用表达」段，避免误收其他段落的反引号内容。

    实际踩到的坑：self_improvement 写入的怀疑记录也用反引号包裹
    时间戳和群号，例如：
        - `2026-08-31T11:03:07+08:00` 群 `-1009000000001`：
    若全文扫描，时间戳会被当成匹配模式。虽然正常发言不会包含
    时间戳而不至于误拦，但群号会——讨论群号时就被拦了。
    """

    text = """# SKILL.md

## ⚠️ 应避免的表达

- `2026-08-31T11:03:07+08:00` 群 `-1009000000001`：某次被怀疑

## 禁用表达（发言前自检）

- `作为一个ai`：直接自称
- `假false`：模型污染
"""

    store = LessonStore.from_markdown(text)

    assert "作为一个ai" in store.patterns
    assert "假false" in store.patterns
    assert not any("2026-" in p for p in store.patterns), "时间戳被误当模式"
    assert not any("-1009000000001" == p for p in store.patterns), "群号被误当模式"


def test_missing_section_yields_empty_store() -> None:
    """没有「禁用表达」段时返回空库，不应退化成全文扫描。"""

    text = """# SKILL.md

## 统计

- `随便一个反引号内容`
"""

    store = LessonStore.from_markdown(text)

    assert store.patterns == ()
