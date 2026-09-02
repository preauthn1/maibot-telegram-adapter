"""在线作息调度测试。

根因（2026-09-02 实测）：
- 每次调用 Telegram API，服务器把账号标记为在线 5 分钟
- mark_read 对每条入站消息都调 send_read_acknowledge
- 该群入站消息中位间隔 8.7 秒、99% < 5 分钟
- 结果：全天仅 2.5 小时可能离线，其余 21.5 小时持续在线

24 小时在线是最难辩解的机器特征——真人有睡眠、通勤、上课。
Telegram 客服看到这个作息可直接认定 spam。

解决思路是**解耦**：
把「是否该在线」的决策从「发送消息」这个动作里剥离出来，
交给独立的作息调度器。发送链路只负责申请上线，
调度器根据作息表决定当前是否允许在线、以及何时强制离线。
"""

from datetime import datetime, timezone, timedelta

import pytest

from plugins.telegram_user_adapter.presence_schedule import (
    PresenceWindow,
    PresenceSchedule,
)

_CN_TZ = timezone(timedelta(hours=8))


def _at(hour: int, minute: int = 0) -> datetime:
    """构造北京时间的某个时刻。"""

    return datetime(2026, 9, 3, hour, minute, tzinfo=_CN_TZ)


class TestSleepWindow:
    """睡眠时段必须强制离线——这是最像人的一条。

    窗口 00:00-08:00 来自群里真实活跃度低谷（69688 条入站消息统计），
    不是拍脑袋定的。
    """

    @pytest.mark.parametrize("hour", [1, 2, 3, 4, 5, 6, 7])
    def test_asleep_at_night(self, hour: int) -> None:
        sched = PresenceSchedule()

        assert sched.allows_online(_at(hour)) is False

    @pytest.mark.parametrize("hour", [10, 14, 20, 22])
    def test_awake_in_daytime(self, hour: int) -> None:
        sched = PresenceSchedule()

        assert sched.allows_online(_at(hour)) is True

    def test_wakes_at_eight(self) -> None:
        """08:00 群消息量回升到 178/h，超过低谷阈值，应醒来。"""

        sched = PresenceSchedule()

        assert sched.allows_online(_at(8)) is True

    def test_seven_am_still_asleep(self) -> None:
        """07:00 群消息量 148/h 仍在低谷阈值(154.5)以下，应还在睡。

        回归测试：最初拍脑袋定成 00:00-07:00，漏了 7 点这一小时。
        """

        sched = PresenceSchedule()

        assert sched.allows_online(_at(7)) is False

    def test_sleep_window_crosses_midnight(self) -> None:
        """睡眠时段跨零点，00:30 必须判定为睡着。"""

        sched = PresenceSchedule()

        assert sched.allows_online(_at(0, 30)) is False


class TestCustomWindows:
    """作息表可配置——不同人设需要不同作息。"""

    def test_custom_offline_window(self) -> None:
        """上课时段离线。"""

        sched = PresenceSchedule(
            windows=[PresenceWindow(start_hour=8, end_hour=12, online=False)]
        )

        assert sched.allows_online(_at(9)) is False
        assert sched.allows_online(_at(13)) is True

    def test_empty_windows_always_online(self) -> None:
        """没有配置任何窗口时不限制——保守默认，不能让功能反而卡死发送。"""

        sched = PresenceSchedule(windows=[])

        assert sched.allows_online(_at(3)) is True


class TestSessionLinger:
    """会话级驻留：对话期间保持在线，结束后下线。

    原实现是「消息级」——每条消息发完就想下线（4-15 秒），
    但下一次 API 调用立刻把在线续期，等于白做。
    改成会话级后，驻留时长要覆盖一次完整对话。
    """

    def test_linger_covers_conversation(self) -> None:
        sched = PresenceSchedule()

        seconds = sched.session_linger_seconds()

        # 必须显著长于原来的 4-15 秒，否则仍会被 API 调用续期覆盖
        assert seconds >= 60, "驻留太短，会被下一次 API 调用续期覆盖"

    def test_linger_is_randomized(self) -> None:
        """固定时长本身就是机器特征。"""

        sched = PresenceSchedule()
        samples = {sched.session_linger_seconds() for _ in range(50)}

        assert len(samples) > 1, "驻留时长必须有随机性"


class TestReadSuppression:
    """离线期间必须抑制已读回执。

    这是解耦的关键：mark_read 每条消息调一次 API，
    在 5 万人群里等于永不停歇地续期在线（实测中位间隔 8.7 秒）。
    离线时段必须停掉，否则作息表形同虚设。
    """

    def test_suppresses_read_when_offline(self) -> None:
        sched = PresenceSchedule()

        assert sched.allows_read_receipt(_at(3)) is False

    def test_allows_read_when_online(self) -> None:
        sched = PresenceSchedule()

        assert sched.allows_read_receipt(_at(14)) is True


class TestTimezoneHandling:
    """时区必须显式处理——此前踩过 UTC/本地混用的坑。"""

    def test_naive_datetime_treated_as_local(self) -> None:
        """无时区的时间按北京时间处理，不能当成 UTC。"""

        sched = PresenceSchedule()
        naive_3am = datetime(2026, 9, 3, 3, 0)

        assert sched.allows_online(naive_3am) is False

    def test_utc_datetime_converted(self) -> None:
        """UTC 19:00 = 北京 03:00，应判定为睡眠。"""

        sched = PresenceSchedule()
        utc_time = datetime(2026, 9, 2, 19, 0, tzinfo=timezone.utc)

        assert sched.allows_online(utc_time) is False
