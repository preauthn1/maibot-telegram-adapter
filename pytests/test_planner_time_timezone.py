"""Planner prompt 中"当前时间"的时区回归测试。

真实事故：服务器时区为 UTC，Planner prompt 注入的时间是 UTC，
模型据此在北京时间凌晨 1 点对群里说"现在才五点"。
用户当场手动删除了那条消息——这是直接的身份暴露。

修复有两层，本测试锁第二层（代码层）：
1. 运维层：系统时区设为 Asia/Shanghai
2. 代码层：显式绑定 UTC+8，不依赖系统时区

只做第 1 层是不够的——运维改一次时区就会静默复发。
"""

from datetime import datetime, timedelta, timezone

from src.maisaka.chat_loop_service import MaisakaChatLoopService

_CN_TZ = timezone(timedelta(hours=8))


def test_current_time_message_uses_china_timezone() -> None:
    """注入 Planner 的当前时间必须是 UTC+8。"""

    message = MaisakaChatLoopService._build_current_time_user_message()
    expected_hour = datetime.now(_CN_TZ).hour

    # 形如 "时间：2026-09-02 01:02:03"
    hour_text = message.split(" ")[-1].split(":")[0]

    assert int(hour_text) == expected_hour, (
        f"Planner 收到的小时 {hour_text} 与北京时间 {expected_hour} 不符——"
        "模型会照此说错时间，属于身份暴露"
    )


def test_does_not_depend_on_system_timezone(monkeypatch) -> None:
    """即使系统时区被改回 UTC，注入的时间仍应是北京时间。

    这是本测试存在的核心理由：运维层的 timedatectl 修复不可依赖。
    """

    import time as time_module

    monkeypatch.setenv("TZ", "UTC")
    if hasattr(time_module, "tzset"):
        time_module.tzset()

    try:
        message = MaisakaChatLoopService._build_current_time_user_message()
        expected_hour = datetime.now(_CN_TZ).hour
        hour_text = message.split(" ")[-1].split(":")[0]

        assert int(hour_text) == expected_hour, (
            "系统时区设为 UTC 后注入时间跟着变了——说明仍在依赖系统时区"
        )
    finally:
        # 还原，避免污染同进程内的后续测试
        monkeypatch.delenv("TZ", raising=False)
        if hasattr(time_module, "tzset"):
            time_module.tzset()


def test_source_has_no_naive_now_in_time_message() -> None:
    """源码层锁死：构建时间消息处不得使用裸 datetime.now()。

    裸调用是隐式依赖系统时区，正是本次事故的根因。
    """

    from pathlib import Path

    source = Path("src/maisaka/chat_loop_service.py").read_text(encoding="utf-8")
    start = source.index("_build_current_time_user_message")
    end = source.index("_append_time_user_message", start)
    body = source[start:end]

    # 只检查真正的代码行：docstring 里会引用 "datetime.now()" 来解释
    # 为什么不能用它，那属于说明而非调用，不应触发断言。
    code_lines = []
    in_docstring = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)

    assert "datetime.now()" not in code, (
        "构建 Planner 时间消息时使用了裸 datetime.now()，"
        "会跟随系统时区导致说错时间"
    )
    assert "_CN_TZ" in code, "未显式绑定 UTC+8 时区"
