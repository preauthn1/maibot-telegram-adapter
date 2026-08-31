"""分段发送时预算必须按段检查。

审计发现 codecs/outbound.py 的 send_outbound_message：
- ``check()`` 只在进入函数时调一次
- ``record()`` 在段循环内每段一次（注释还明确说「按段计数」）

一条回复被 response_splitter 拆成 N 段时，只检查了 1 次却记了 N 笔。
探针实测 10 段一次全发，minute_limit=5 时 last_minute 记到 10，
超限 100%。send_budget 存在的唯一目的（防爆发式连发）被绕过。

真实证据：封禁当天 15:18 单分钟 8 条，5 个分钟超过 5 条/分。
而这个账号正是因反垃圾系统限制 + 人工确认举报被封的。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.send_budget import SendBudget  # noqa: E402


def test_budget_blocks_within_burst() -> None:
    """预算耗尽后，同一批次的后续段必须被拦。

    这是「按段检查」的核心：不能只在批次开头查一次。
    """

    budget = SendBudget(minute_limit=3, hourly_limit=100)

    allowed_count = 0
    for _ in range(10):
        allowed, _reason = budget.check()
        if not allowed:
            break
        budget.record()
        allowed_count += 1

    assert allowed_count == 3, (
        f"minute_limit=3 却放行了 {allowed_count} 段——"
        "说明检查没有跟着每一段走"
    )


def test_outbound_checks_budget_per_segment() -> None:
    """源码结构断言：check() 必须出现在段循环内部。

    只在函数入口检查一次的话，一条回复拆 10 段就会超限 10 倍。
    """

    path = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "telegram_user_adapter"
        / "codecs"
        / "outbound.py"
    )
    source = path.read_text(encoding="utf-8")

    lines = source.splitlines()

    # 找到段循环的位置
    loop_line = next(
        (i for i, line in enumerate(lines) if "for seg in payloads:" in line),
        None,
    )
    assert loop_line is not None, "找不到分段发送循环"

    # 找 record() 与 check() 各自的位置
    record_line = next(
        (i for i, line in enumerate(lines) if "self._send_budget.record()" in line),
        None,
    )
    check_lines = [
        i for i, line in enumerate(lines) if "self._send_budget.check()" in line
    ]

    assert record_line is not None and record_line > loop_line, (
        "record() 应该在段循环内"
    )
    assert any(i > loop_line for i in check_lines), (
        f"check() 只出现在第 {check_lines} 行，全部在段循环（第 {loop_line} 行）之前——"
        "按条检查、按段记账，一条拆 N 段就超限 N 倍"
    )


def test_topic_route_survives_all_segments() -> None:
    """话题群多段发送时，第 2 段起必须仍留在同一话题。

    审计发现原实现 `current_reply = reply_to if not sent_any else None`
    把 topic 路由和引用一起抹掉，第 2、3 段掉进 General：

      sent reply_to=458347 '第一句'
      sent reply_to=None   '第二句'   ← 落到 General
      sent reply_to=None   '第三句'

    上下文断裂，在人工审核视角极为扎眼。
    """

    path = (
        Path(__file__).resolve().parents[1]
        / "plugins"
        / "telegram_user_adapter"
        / "codecs"
        / "outbound.py"
    )
    source = path.read_text(encoding="utf-8")

    assert "current_reply = reply_to if not sent_any else None" not in source, (
        "旧的一刀切写法还在：它会把 topic 路由和引用一起清空"
    )
    assert "current_reply = parsed_thread_id" in source, (
        "后续段没有回落到 topic 根消息 ID，会掉进 General"
    )
