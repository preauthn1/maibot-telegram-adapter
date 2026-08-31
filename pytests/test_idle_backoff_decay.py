"""空闲退避衰减与时钟源测试。

两个实测问题：
1. ``_count`` 只在发言时清零，消息稀疏的群会长期卡在封顶退避
   （实测某低频群卡 35 分钟、Project X 卡 14 分钟），而活跃群
   1-4 分钟就能靠消息量自然绕过。
2. 原本用 ``time.time()``，NTP 校正时会导致退避时长错乱；
   同项目 reasoning_engine 用的是 ``monotonic()``。
"""

from __future__ import annotations

from typing import Any

import pytest

from src.maisaka.idle_backoff import IDLE_DECAY_SECONDS, IdleBackoffController


class _StubStream:
    is_group_session = True


class _StubRuntime:
    """只提供 IdleBackoffController 需要的最小接口。"""

    log_prefix = "[test]"
    chat_stream = _StubStream()

    def _is_focus_mode_active_for_current_chat(self) -> bool:
        return False

    def _defer_message_turn_check(self, seconds: float) -> None:
        del seconds


@pytest.fixture()
def controller() -> IdleBackoffController:
    return IdleBackoffController(_StubRuntime())  # type: ignore[arg-type]


def test_uses_monotonic_clock() -> None:
    """必须用单调时钟——NTP 回拨会让 time.time() 算出错误的剩余时间。"""

    source = (
        __import__("pathlib").Path("src/maisaka/idle_backoff.py").read_text(encoding="utf-8")
    )
    assert "time.time()" not in source, "仍在使用 wall clock，NTP 校正会导致退避错乱"
    assert "time.monotonic()" in source


def test_idle_count_accumulates(controller: IdleBackoffController) -> None:
    """连续空闲应当累加计数。"""

    for _ in range(3):
        controller.record_cycle_result("planner_no_tool_end")
    assert controller._count == 3


def test_speaking_resets_count(controller: IdleBackoffController) -> None:
    """真的发言后计数归零。"""

    for _ in range(5):
        controller.record_cycle_result("planner_no_tool_end")
    controller.record_cycle_result("tool_end:reply")
    assert controller._count == 0


def test_decay_lowers_count_after_silence(
    controller: IdleBackoffController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """⚠️ 核心修复：群安静一段时间后退避要回落，不能永远卡在封顶。"""

    import src.maisaka.idle_backoff as mod

    fake = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: fake["t"])

    # 先累到较高计数
    for _ in range(8):
        controller.record_cycle_result("planner_no_tool_end")
    assert controller._count == 8

    # 静默两个衰减周期后再来一轮
    fake["t"] += IDLE_DECAY_SECONDS * 2 + 1
    controller.record_cycle_result("planner_no_tool_end")

    # 应当降了 2 级再 +1，而不是直接 9
    assert controller._count < 8, f"计数没有衰减，仍为 {controller._count}"


def test_decay_never_goes_negative(
    controller: IdleBackoffController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """长时间静默不该把计数压成负数。"""

    import src.maisaka.idle_backoff as mod

    fake = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: fake["t"])

    controller.record_cycle_result("planner_no_tool_end")
    fake["t"] += IDLE_DECAY_SECONDS * 100
    controller.record_cycle_result("planner_no_tool_end")

    assert controller._count >= 0


def test_short_silence_does_not_decay(
    controller: IdleBackoffController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """短暂间隔不该触发衰减，否则退避形同虚设。"""

    import src.maisaka.idle_backoff as mod

    fake = {"t": 1000.0}
    monkeypatch.setattr(mod.time, "monotonic", lambda: fake["t"])

    for _ in range(4):
        fake["t"] += 5.0
        controller.record_cycle_result("planner_no_tool_end")

    assert controller._count == 4


def test_reset_clears_decay_anchor(controller: IdleBackoffController) -> None:
    """reset 要一并清掉衰减锚点，避免残留状态影响下一轮。"""

    controller.record_cycle_result("planner_no_tool_end")
    controller.reset()
    assert controller._count == 0
    assert controller._last_cycle_at == 0.0
