"""SKILL.md 段落保留测试。

审计发现的 P0：``_rewrite_skill_file()`` 用固定模板整体重写 SKILL.md，
不读旧文件、不做合并。而 ``record_outcome()`` 在**每一次发言反馈**时
都会调用它。

后果是双重的：
1. 人工维护的「禁用表达」段落（22 条身份泄漏模式）被永久删除
2. ``pre_send_review`` 只扫描该段落，段落没了 → 模式数归零 →
   发言前身份泄漏自检**完全失效**，而且是静默失效

实测（真实文件副本 + 一次 record_outcome）：
    BEFORE: 行数 66 | 禁用模式 22 条
    AFTER : 行数 29 | 禁用模式  0 条

修复方向：程序只重写自己拥有的段落，其余内容原样保留。
"""

from pathlib import Path

import asyncio
import logging
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.pre_send_review import LessonStore  # noqa: E402
from telegram_user_adapter.self_improvement import (  # noqa: E402
    ChatOutcome,
    SelfImprovementStore,
)

_HUMAN_SECTION = """

## 禁用表达（发言前自检）

身份泄漏类：

- `作为一个ai`：直接自称
- `as an ai`：英文变体
- `我是一个语言模型`：直接自称
"""


def _make_store(tmp_path: Path) -> SelfImprovementStore:
    """构造一个指向临时目录的存储。"""

    return SelfImprovementStore(tmp_path, logging.getLogger("test"), enabled=True)


def test_human_section_survives_rewrite(tmp_path: Path) -> None:
    """程序重写统计时，人工维护的段落必须原样保留。

    这是审计发现的 P0：每次发言反馈都会抹掉人工段落，
    导致发言前自检静默失效。
    """

    store = _make_store(tmp_path)
    # 模拟人工在 SKILL.md 里补写禁用表达段
    store.skill_path.write_text(
        store.skill_path.read_text(encoding="utf-8") + _HUMAN_SECTION,
        encoding="utf-8",
    )

    before = LessonStore.from_markdown(store.skill_path.read_text(encoding="utf-8"))
    assert len(before.patterns) == 3, "前置条件：人工段落已写入"

    # 触发一次程序重写
    asyncio.run(
        store.record_outcome(ChatOutcome(chat_id="chat-a", text="随便说一句"))
    )

    after = LessonStore.from_markdown(store.skill_path.read_text(encoding="utf-8"))
    assert len(after.patterns) == 3, (
        f"人工段落被抹掉了：{len(before.patterns)} → {len(after.patterns)} 条。"
        "发言前自检会静默失效。"
    )


def test_generated_section_still_updates(tmp_path: Path) -> None:
    """保留人工段落的同时，程序段落仍要能正常更新。"""

    store = _make_store(tmp_path)
    store.skill_path.write_text(
        store.skill_path.read_text(encoding="utf-8") + _HUMAN_SECTION,
        encoding="utf-8",
    )

    asyncio.run(
        store.record_outcome(ChatOutcome(chat_id="chat-a", text="第一句"))
    )
    text = store.skill_path.read_text(encoding="utf-8")

    assert "## 统计" in text
    assert "累计发言：1" in text


def test_repeated_rewrites_do_not_duplicate(tmp_path: Path) -> None:
    """反复重写不应让人工段落被复制多份。"""

    store = _make_store(tmp_path)
    store.skill_path.write_text(
        store.skill_path.read_text(encoding="utf-8") + _HUMAN_SECTION,
        encoding="utf-8",
    )

    for index in range(3):
        asyncio.run(
            store.record_outcome(ChatOutcome(chat_id="chat-a", text=f"第{index}句"))
        )

    text = store.skill_path.read_text(encoding="utf-8")

    assert text.count("## 禁用表达") == 1, "人工段落被重复追加"
    assert text.count("## 统计") == 1, "程序段落被重复追加"


def test_inline_marker_mention_does_not_eat_content() -> None:
    """人工文档里提到标记字符串时，不该吞掉中间的说明文字。

    标记文本本身就写着「请勿手工编辑」，运维在文档里解释这套
    机制是极自然的行为——结果恰好触发数据丢失。

    原实现用 str.find 子串搜索首个 BEGIN 和首个 END，人工正文里
    内联提到这两个词就会被当成真标记，中间的说明全部消失，
    且合并结果里出现 BEGIN×2 END×2，文件结构永久损坏。
    """

    from telegram_user_adapter.self_improvement import (
        _AUTO_BEGIN,
        _AUTO_END,
        _merge_generated_block,
    )

    existing = f"""# 说话习惯

## 机制说明

程序在 `{_AUTO_BEGIN}` 与 `{_AUTO_END}` 之间写统计，
这段说明极其重要，请勿删除。

{_AUTO_BEGIN}
- 旧的程序内容
{_AUTO_END}

## ⚠️ 禁用表达

- 作为一个AI
"""

    merged = _merge_generated_block(existing, f"{_AUTO_BEGIN}\n- 新内容\n{_AUTO_END}")

    assert "这段说明极其重要，请勿删除" in merged, "人工说明文字被吞掉了"
    assert "作为一个AI" in merged, "禁用表达段丢失"
    assert merged.count(_AUTO_BEGIN) == 2, (
        f"标记数量异常（{merged.count(_AUTO_BEGIN)} 个 BEGIN）："
        "正文里的内联提及 + 真标记各 1 个才对，结构不该被破坏"
    )
    assert "旧的程序内容" not in merged, "旧的程序段应被替换"
    assert "新内容" in merged, "新内容没写进去"
