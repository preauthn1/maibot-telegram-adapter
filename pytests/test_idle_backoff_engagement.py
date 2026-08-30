"""空闲退避「参与窗口」测试。

回归实测事故：账号在群里回了两条后，对方连续追问三句，
它却因退避升到 240 秒而完全没反应，看起来像聊到一半人间蒸发。
"""

from __future__ import annotations

import time
from typing import Any, List

import pytest

from src.maisaka import idle_backoff as ib
from src.maisaka.idle_backoff import IdleBackoffController


class _FakeStream:
    is_group_session = True


class _FakeRuntime:
    """最小化 runtime 替身。"""

    log_prefix = "[测试群]"

    def __init__(self) -> None:
        self.chat_stream = _FakeStream()
        self.deferred: List[float] = []

    def _is_focus_mode_active_for_current_chat(self) -> bool:
        return False

    def _defer_message_turn_check(self, seconds: float) -> None:
        self.deferred.append(seconds)


@pytest.fixture
def controller() -> IdleBackoffController:
    return IdleBackoffController(_FakeRuntime())


def _drive_idle(ctrl: IdleBackoffController, times: int) -> None:
    """连续制造 times 次「不回复」结果。"""

    for _ in range(times):
        ctrl.record_cycle_result("planner_no_tool_end")


def test_backoff_grows_when_not_engaged(controller: IdleBackoffController) -> None:
    """长时间没发过言时，退避照常指数增长。

    这是原有行为，不能因为修复而丢失——群里没自己的事就该安静。
    """

    _drive_idle(controller, 6)

    assert controller._get_backoff_seconds() > ib.ENGAGEMENT_MAX_BACKOFF_SECONDS


def test_backoff_capped_right_after_speaking(controller: IdleBackoffController) -> None:
    """刚发过言时退避被压低，不会一路涨到几分钟。

    回归事故：退避升到 240 秒，错过了对方的连续追问。
    """

    controller.note_spoke()
    _drive_idle(controller, 6)

    assert controller._get_backoff_seconds() <= ib.ENGAGEMENT_MAX_BACKOFF_SECONDS


def test_engagement_window_expires(controller: IdleBackoffController) -> None:
    """参与窗口过期后恢复正常退避，避免永久高频打扰群聊。"""

    controller.note_spoke()
    controller._last_spoke_at = time.time() - ib.ENGAGEMENT_WINDOW_SECONDS - 1
    _drive_idle(controller, 6)

    assert controller._get_backoff_seconds() > ib.ENGAGEMENT_MAX_BACKOFF_SECONDS


def test_speaking_opens_engagement_window(controller: IdleBackoffController) -> None:
    """非空闲结束（真的发了言）应开启参与窗口。"""

    assert not controller._is_engaged()

    controller.record_cycle_result("reply_sent")

    assert controller._is_engaged(), "发言后应进入参与窗口"


def test_engaged_bypass_threshold_is_lowered() -> None:
    """刚发过言时，两条新消息即可打断退避。

    对方追问两三句还不理，就是聊到一半人间蒸发。
    """

    runtime = _FakeRuntime()
    ctrl = IdleBackoffController(runtime)
    ctrl.note_spoke()
    _drive_idle(ctrl, 6)

    # 两条待处理消息应当直接绕过退避。
    assert not ctrl.should_delay(pending_count=2)


def test_not_engaged_keeps_configured_threshold() -> None:
    """未处于参与窗口时，沿用配置的绕过阈值（默认 6）。"""

    runtime = _FakeRuntime()
    ctrl = IdleBackoffController(runtime)
    _drive_idle(ctrl, 6)

    assert ctrl.should_delay(pending_count=2), "没发过言时不该被 2 条消息打断"


def test_private_session_never_backs_off() -> None:
    """私聊不适用退避，原有行为不得改变。"""

    runtime = _FakeRuntime()
    runtime.chat_stream.is_group_session = False
    ctrl = IdleBackoffController(runtime)

    _drive_idle(ctrl, 6)

    assert not ctrl.should_delay(pending_count=1)
