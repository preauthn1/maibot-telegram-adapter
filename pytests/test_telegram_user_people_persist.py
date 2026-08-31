"""人物记忆的持久化测试。

记忆的价值在于跨会话——「这人搞前端」「那位有台 NAS」必须活过
进程重启，否则每次重启都从零开始，等于没记。

原实现是纯内存 dict，没有任何落盘逻辑。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.people_memory import PeopleMemory  # noqa: E402


def test_facts_survive_restart(tmp_path: Path) -> None:
    """记忆必须活过进程重启，否则跨会话记人就是空话。"""

    store_path = tmp_path / "people.json"

    first = PeopleMemory(storage_path=store_path)
    first.remember("alice", "我在深圳做前端")
    first.remember("alice", "我家有台群晖 NAS")
    first.save()

    # 模拟重启：全新实例读同一个文件
    second = PeopleMemory(storage_path=store_path)

    facts = [fact.text for fact in second.recall("alice")]
    assert "我在深圳做前端" in facts
    assert "我家有台群晖 NAS" in facts


def test_missing_file_starts_empty(tmp_path: Path) -> None:
    """首次运行没有文件时应当正常启动，而不是崩。"""

    memory = PeopleMemory(storage_path=tmp_path / "not_created_yet.json")

    assert memory.known_people() == 0


def test_corrupted_file_does_not_crash(tmp_path: Path) -> None:
    """文件损坏时不应让插件起不来。

    按 AGENTS.md「错误要及时完整暴露」：这里不静默吞掉，
    而是把损坏文件改名留证，然后以空记忆启动——
    人物记忆丢了不该导致整个账号下线。
    """

    store_path = tmp_path / "people.json"
    store_path.write_text("{ 这不是合法 JSON", encoding="utf-8")

    memory = PeopleMemory(storage_path=store_path)

    assert memory.known_people() == 0
    # 损坏的原文件应被保留下来供排查
    assert list(tmp_path.glob("people.json.corrupt-*")), "损坏文件未留证"


def test_save_is_atomic(tmp_path: Path) -> None:
    """写入要用临时文件 + 替换，避免写一半断电留下半个文件。"""

    store_path = tmp_path / "people.json"

    memory = PeopleMemory(storage_path=store_path)
    memory.remember("bob", "我用 Arch Linux")
    memory.save()

    # 落盘后不应残留临时文件
    assert store_path.exists()
    assert not list(tmp_path.glob("*.tmp")), "残留临时文件"


def test_no_path_means_memory_only(tmp_path: Path) -> None:
    """不给路径时退化为纯内存，save() 不应报错。"""

    memory = PeopleMemory()
    memory.remember("carol", "我在做 Rust 编译器")

    memory.save()  # 不该抛异常

    assert len(memory.recall("carol")) == 1


def test_capacity_limit_persists(tmp_path: Path) -> None:
    """淘汰后的结果要正确落盘，不能把已淘汰的旧事实写回去。"""

    store_path = tmp_path / "people.json"

    first = PeopleMemory(storage_path=store_path, max_facts_per_person=3)
    for index in range(5):
        first.remember("dave", f"我用编号{index}的设备")
    first.save()

    second = PeopleMemory(storage_path=store_path, max_facts_per_person=3)

    assert len(second.recall("dave")) == 3


def test_duplicate_fact_reports_not_new() -> None:
    """已知事实要返回 False，否则会不停触发无谓的写盘。

    调用方用返回值累计"脏计数"决定何时落盘。群里反复出现
    同一句话（转发、复读）时，若每次都算新增就会持续写盘。
    """

    memory = PeopleMemory()

    assert memory.remember("alice", "我在深圳做前端") is True
    assert memory.remember("alice", "我在深圳做前端") is False
    assert memory.remember("alice", "  她在深圳做前端  ") is False, "去空白后应视为同一条"

    assert len(memory.recall("alice")) == 1


def test_noise_is_rejected() -> None:
    """真实群聊里的噪音不该被当成人物事实。

    端到端跑封禁当天 60925 条真实入站消息时，原实现（黑名单：
    只要不含"正在""刚才"等词就算事实）判定 22% 是稳定事实，
    记下 1071 人、605 KB，内容全是 URL、引用块、"哦哦"、"已销号"。

    这些注入 prompt 只会污染上下文，比没有记忆更糟。
    """

    from telegram_user_adapter.people_memory import is_durable_fact

    noise = [
        "哦哦",
        "已销号",
        "怎么直接撤回了",
        "https://example.com/[媒体]",
        "[回复<某人:1009000000001>：某句话]，说：好似",
        "第三方应用商店",
        "@example_user 想你了哥哥",
        "我现在变肉鸡了？",
        "辣子鸡 发我工具",
        "这群只会写chromium套壳gui的都该突突了",
    ]

    wrongly_learned = [text for text in noise if is_durable_fact(text)]

    assert not wrongly_learned, f"这些噪音被当成了人物事实：{wrongly_learned}"


def test_real_facts_are_accepted() -> None:
    """真正的自我陈述仍要能识别——收紧不能收死。"""

    from telegram_user_adapter.people_memory import is_durable_fact

    facts = [
        "我在深圳做前端",
        "我用的是 Arch Linux",
        "我家里有台群晖 NAS",
        "我是做后端的",
        "我平时用 Kotlin 写安卓",
    ]

    missed = [text for text in facts if not is_durable_fact(text)]

    assert not missed, f"这些是真实事实却没识别：{missed}"


def test_temporary_state_still_rejected() -> None:
    """临时状态仍要拒收——那是原设计的核心约束。"""

    from telegram_user_adapter.people_memory import is_durable_fact

    temporary = [
        "我正在装系统",
        "我刚才重启了路由",
        "我马上要出门了",
    ]

    wrongly_learned = [text for text in temporary if is_durable_fact(text)]

    assert not wrongly_learned, f"临时状态被当成事实：{wrongly_learned}"
