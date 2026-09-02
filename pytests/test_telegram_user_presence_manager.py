"""PresenceManager 与作息调度解耦后的行为测试。

关键约束：
1. 睡眠时段拒绝上线（原实现只要发消息就上线，不看时间）
2. 驻留时长来自调度器（分钟级，不再是 4-15 秒）
3. 状态上报失败不能中断发送
"""

from datetime import timedelta, timezone
from typing import Any, List

import asyncio

import pytest

from plugins.telegram_user_adapter.presence import PresenceManager
from plugins.telegram_user_adapter.presence_schedule import (
    PresenceSchedule,
    PresenceWindow,
)

_CN_TZ = timezone(timedelta(hours=8))


class _StubClient:
    """记录 UpdateStatusRequest 调用的假客户端。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.calls: List[bool] = []
        self._fail = fail

    @property
    def client(self) -> Any:
        return self

    async def __call__(self, request: Any) -> Any:
        if self._fail:
            raise RuntimeError("模拟网络失败")
        self.calls.append(bool(getattr(request, "offline", False)))
        return None


class _StubLogger:
    def __init__(self) -> None:
        self.messages: List[str] = []

    def debug(self, msg: str) -> None:
        self.messages.append(msg)

    def info(self, msg: str) -> None:
        self.messages.append(msg)

    def warning(self, msg: str) -> None:
        self.messages.append(msg)

    def error(self, msg: str) -> None:
        self.messages.append(msg)


def _sleeping_schedule() -> PresenceSchedule:
    """构造一个"全天都在睡觉"的作息，便于确定性测试。"""

    return PresenceSchedule(
        windows=[PresenceWindow(start_hour=0, end_hour=24, online=False)]
    )


def _awake_schedule() -> PresenceSchedule:
    return PresenceSchedule(windows=[])


class TestScheduleGatesOnline:
    """作息表必须能拦住上线请求。"""

    def test_refuses_online_during_sleep(self) -> None:
        """睡眠时段即使要发言也不上线。

        这是与原实现最大的区别：原来 go_online 无条件上线。
        """

        client = _StubClient()
        mgr = PresenceManager(
            client, _StubLogger(), schedule=_sleeping_schedule()
        )

        asyncio.run(mgr.go_online())

        assert mgr.is_online is False
        assert client.calls == [], "睡眠时段不应有任何状态上报"

    def test_allows_online_when_awake(self) -> None:
        client = _StubClient()
        mgr = PresenceManager(client, _StubLogger(), schedule=_awake_schedule())

        asyncio.run(mgr.go_online())

        assert mgr.is_online is True
        assert client.calls == [False], "应上报一次在线"


class TestLingerFromSchedule:
    """驻留时长必须来自调度器，不再硬编码 4-15 秒。"""

    def test_uses_schedule_linger(self) -> None:
        schedule = PresenceSchedule(
            windows=[], linger_min=100.0, linger_max=100.0
        )
        mgr = PresenceManager(_StubClient(), _StubLogger(), schedule=schedule)

        assert mgr.linger_seconds() == pytest.approx(100.0)

    def test_linger_is_minutes_not_seconds(self) -> None:
        """回归：默认驻留必须是分钟级。

        原来 4-15 秒毫无意义——入站消息中位间隔 8.7 秒，
        下一条消息的 mark_read 立刻把在线续期。
        """

        mgr = PresenceManager(
            _StubClient(), _StubLogger(), schedule=PresenceSchedule()
        )

        assert mgr.linger_seconds() >= 60.0


class TestFailureIsolation:
    """状态上报失败不能中断发送。"""

    def test_online_failure_does_not_raise(self) -> None:
        mgr = PresenceManager(
            _StubClient(fail=True), _StubLogger(), schedule=_awake_schedule()
        )

        asyncio.run(mgr.go_online())

        assert mgr.is_online is False, "上报失败不应标记为在线"

    def test_force_offline_survives_failure(self) -> None:
        mgr = PresenceManager(
            _StubClient(fail=True), _StubLogger(), schedule=_awake_schedule()
        )

        # 不应抛异常
        asyncio.run(mgr.force_offline())


class TestLockNotHeldDuringNetworkIO:
    """网络 IO 不得在锁内进行。

    实测回归：原实现在锁内 await _set_status()（Telegram API 调用），
    代理抖动时 force_offline 被拖住 2.75 秒——插件 shutdown 卡顿。
    修法是锁内只做状态抢占，锁外发请求。
    """

    def test_force_offline_not_blocked_by_slow_network(self) -> None:
        """下线任务卡在网络 IO 时，force_offline 不应被拖住。"""

        class _SlowClient:
            def __init__(self) -> None:
                self.calls: List[bool] = []

            @property
            def client(self) -> Any:
                return self

            async def __call__(self, request: Any) -> Any:
                await asyncio.sleep(2.0)
                self.calls.append(bool(getattr(request, "offline", False)))
                return None

        async def scenario() -> float:
            mgr = PresenceManager(
                _SlowClient(),
                _StubLogger(),
                schedule=PresenceSchedule(
                    windows=[], linger_min=0.05, linger_max=0.05
                ),
            )
            await mgr.go_online()
            await mgr.schedule_offline()
            await asyncio.sleep(0.3)  # 让下线任务进入网络 IO

            import time

            start = time.monotonic()
            await asyncio.wait_for(mgr.force_offline(), timeout=8)
            return time.monotonic() - start

        elapsed = asyncio.run(scenario())

        assert elapsed < 1.0, (
            f"force_offline 被阻塞 {elapsed:.2f}s，说明网络 IO 仍在锁内"
        )


class TestReadReceiptGate:
    """已读回执必须受作息约束——这是 24 小时在线的直接成因。"""

    def test_blocks_read_during_sleep(self) -> None:
        mgr = PresenceManager(
            _StubClient(), _StubLogger(), schedule=_sleeping_schedule()
        )

        assert mgr.allows_read_receipt() is False

    def test_allows_read_when_awake(self) -> None:
        mgr = PresenceManager(
            _StubClient(), _StubLogger(), schedule=_awake_schedule()
        )

        assert mgr.allows_read_receipt() is True


class TestBackwardCompatibility:
    """不传 schedule 时必须仍能工作——避免升级即崩。"""

    def test_works_without_schedule(self) -> None:
        client = _StubClient()
        mgr = PresenceManager(client, _StubLogger())

        # 默认作息在白天允许上线；这里只验证不抛异常
        asyncio.run(mgr.go_online())
        asyncio.run(mgr.force_offline())
