"""人物记忆测试（借鉴 Hermes 的记忆分层）。

Hermes 的记忆分两层：
- **durable facts**：跨会话持久的事实（用户偏好、环境约定），
  每轮都注入上下文，要求精炼高信号
- **会话状态**：任务进度、临时上下文，用完即弃，不进长期记忆

我们现在缺的是第一层。SOUL.md 记的是"我是谁"，SKILL.md 记的是
"怎么说话"，但**没有任何地方记"对方是谁"**。

后果很实际：同一个人昨天说过他在用 OpenWrt，今天再聊到路由
我们毫无印象，每次都像第一次见面。真人不是这样的——群友之间
会记得"这人是搞前端的"、"那位有台 NAS"。这种记忆缺失比说错话
更容易让人觉得不对劲。

Hermes 的关键约束也一并借鉴：
- 只存**稳定事实**，不存任务进度（"他昨天在装系统"一周后就是噪音）
- 有容量上限，满了要淘汰，不能无限膨胀
- 声明式陈述，不是指令
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.people_memory import (  # noqa: E402
    PeopleMemory,
    PersonFact,
)


def test_remember_and_recall() -> None:
    """记住一个人的稳定事实，之后能取回。"""

    memory = PeopleMemory(max_facts_per_person=5)
    memory.remember("user-1", "在用 OpenWrt 软路由", now=1000.0)

    facts = memory.recall("user-1")

    assert len(facts) == 1
    assert facts[0].text == "在用 OpenWrt 软路由"


def test_duplicate_fact_not_stored_twice() -> None:
    """同一事实重复出现不应产生副本。"""

    memory = PeopleMemory()
    memory.remember("user-1", "在用 OpenWrt", now=1000.0)
    memory.remember("user-1", "在用 OpenWrt", now=2000.0)

    assert len(memory.recall("user-1")) == 1


def test_capacity_evicts_oldest() -> None:
    """超出容量时淘汰最旧的——记忆不能无限膨胀。"""

    memory = PeopleMemory(max_facts_per_person=3)
    for index in range(5):
        memory.remember("user-1", f"事实{index}", now=1000.0 + index)

    facts = memory.recall("user-1")

    assert len(facts) == 3
    texts = [fact.text for fact in facts]
    assert "事实0" not in texts, "最旧的应被淘汰"
    assert "事实4" in texts, "最新的应保留"


def test_people_are_isolated() -> None:
    """不同人的记忆互不串味——记混人比不记得更糟。"""

    memory = PeopleMemory()
    memory.remember("user-1", "搞前端的", now=1000.0)
    memory.remember("user-2", "有台群晖", now=1000.0)

    assert [f.text for f in memory.recall("user-1")] == ["搞前端的"]
    assert [f.text for f in memory.recall("user-2")] == ["有台群晖"]


def test_recall_unknown_person_is_empty() -> None:
    """没见过的人返回空，不应报错。"""

    assert PeopleMemory().recall("stranger") == []


def test_prompt_block_is_bounded() -> None:
    """注入 prompt 的文本必须有长度上限——记忆是每轮都带的成本。"""

    memory = PeopleMemory(max_facts_per_person=20)
    for index in range(20):
        memory.remember("user-1", f"这是一条比较长的事实描述编号{index}", now=1000.0 + index)

    block = memory.build_prompt_block("user-1", max_chars=200)

    assert len(block) <= 200


def test_prompt_block_empty_for_unknown() -> None:
    """没有记忆时返回空串，不要往 prompt 里塞占位文字。"""

    assert PeopleMemory().build_prompt_block("stranger") == ""


def test_volatile_facts_rejected() -> None:
    """任务进度类的临时状态不该进长期记忆。

    借鉴 Hermes 的约束：'他正在装系统' 一周后就是噪音，
    而 '他用 Arch' 是稳定事实。
    """

    memory = PeopleMemory()

    accepted = memory.remember("user-1", "在用 Arch Linux", now=1000.0)
    rejected = memory.remember("user-1", "正在装系统", now=1000.0)

    assert accepted is True
    assert rejected is False
    assert len(memory.recall("user-1")) == 1


def test_fact_carries_timestamp() -> None:
    """事实要带时间戳，便于淘汰与人工排查。"""

    memory = PeopleMemory()
    memory.remember("user-1", "在深圳", now=1234.0)

    fact = memory.recall("user-1")[0]

    assert isinstance(fact, PersonFact)
    assert fact.created_at == 1234.0
