"""话语权占比闸门：限制短窗口内我们占群里话量的比例。

## 事故背景

2026-09-03 15:22，群里三人先后复读同一句话：

    15:22:34 台风："聊天机器人ban了吧，看了眼疼"
    15:22:43 hiayu 复读
    15:22:50 ca_yuki 复读
    15:22:50 🅱️γ 直接回复我们的消息发 ``/ad``（举报指令）
    15:23:50 🅱️γ："投票組 把這胡說 ban了吧"

诱因：我们把"送家宽"这个群内玩梗当真，连续讨论顺丰、清关、
运费，还在四分钟后又捡回来讲。10 分钟内群里 39 条、我们 11 条。

## 为什么现有闸门拦不住

已有的频率闸门全是**绝对量**——每小时几条、最小间隔几秒、
连发上限几条。但话语权是**相对量**：

    群里热闹时发 11 条 = 2%   没人在意
    群里安静时发 11 条 = 28%  刷屏

全量统计 8210 条消息（09-02 起）证实这不是偶发：

    5 分钟窗口占比：中位 10.8%  P90 31.4%  峰值 75%（12 条里 9 条是我们）
    超过 20% 的时间占了 23.5%

也就是说，**四分之一的时间我们占据群里五分之一以上的话语权**。
15:22 那次是 28%，连 P90 都不到——不是"那次说多了"，
是一直如此，那次刚好有人受不了。

## 两道闸门

1. **占比闸门**：滑动窗口内占比超阈值就闭嘴。
2. **投诉静默**：被点名嫌弃后强制安静一段时间。
   事故中我们自己回了句"好家伙当面投我票行行行 我少说话"，
   然后照发不误——嘴上说说不算数。

## ⚠️ 当前状态：已实现但未接线

本模块通过了单元测试，但**尚未接入任何发送链路**。原因是接线点
需要决策（Planner 决策前 vs 发送前），且 ``note_complaint()``
的触发源要与 doubt_response 的检测结果打通。

未接线不影响现有功能。接线时需要：
    1. 在 plugin.py 入站处理里调用 ``note_inbound()``
    2. 在发送成功后调用 ``note_outbound()``
    3. 在 ``is_doubt_aimed_at_us()`` 命中时调用 ``note_complaint()``
    4. 在 outbound codec 的发送预算检查处加 ``allows_send()``
"""

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Deque, Optional

import random

_CN_TZ = timezone(timedelta(hours=8))

# 默认滑动窗口长度（分钟）。
#
# 取 10 分钟：事故窗口就是这个尺度，且短于此容易被单次多轮对话
# 误伤（真人回一个话题也可能连发三四条），长于此又反应太慢。
_DEFAULT_WINDOW_MINUTES = 10.0

# 占比上限。
#
# 群里真人的自然占比中位是 10.8%，取 20% 作上限——
# 留出一倍余量给正常的多轮对话，同时砍掉 P90（31%）那一段。
_DEFAULT_MAX_SHARE = 0.20

# 判定所需的最小样本数。
#
# 冷群里群消息本来就少，若不设下限，第一句话就会被判成 100% 占比
# 而永久闭嘴。10 条是经验值：够形成比例，又不会拖太久。
_DEFAULT_MIN_SAMPLES = 10

# 被投诉后的静默时长（分钟）。
_DEFAULT_COMPLAINT_SILENCE = 45.0

# 静默时长的随机浮动比例。固定时长本身就是机器特征。
_SILENCE_JITTER = 0.35


class ShareGuard:
    """限制短窗口内的话语权占比。"""

    def __init__(
        self,
        *,
        window_minutes: float = _DEFAULT_WINDOW_MINUTES,
        max_share: float = _DEFAULT_MAX_SHARE,
        min_samples: int = _DEFAULT_MIN_SAMPLES,
        complaint_silence_minutes: float = _DEFAULT_COMPLAINT_SILENCE,
    ) -> None:
        """初始化占比闸门。

        Args:
            window_minutes: 滑动窗口长度（分钟）。
            max_share: 允许的最大占比，``0.20`` 表示 20%。
            min_samples: 触发判定所需的最小窗口样本数。
            complaint_silence_minutes: 被投诉后的静默基准时长。
        """

        self._window = timedelta(minutes=window_minutes)
        self._max_share = max_share
        self._min_samples = min_samples
        self._silence_minutes = complaint_silence_minutes

        self._inbound: Deque[datetime] = deque()
        self._outbound: Deque[datetime] = deque()
        self._silent_until: Optional[datetime] = None

    @staticmethod
    def _now(moment: Optional[datetime]) -> datetime:
        """规整时刻到本地时区。

        Args:
            moment: 待规整时刻；``None`` 表示当前时间。

        Returns:
            datetime: 带时区的本地时间。
        """

        if moment is None:
            return datetime.now(_CN_TZ)
        if moment.tzinfo is None:
            return moment.replace(tzinfo=_CN_TZ)
        return moment.astimezone(_CN_TZ)

    def _trim(self, now: datetime) -> None:
        """丢弃滑出窗口的记录。

        Args:
            now: 当前时刻。
        """

        cutoff = now - self._window
        while self._inbound and self._inbound[0] < cutoff:
            self._inbound.popleft()
        while self._outbound and self._outbound[0] < cutoff:
            self._outbound.popleft()

    def note_inbound(self, moment: Optional[datetime] = None) -> None:
        """记录一条群里的入站消息。

        Args:
            moment: 消息时刻；``None`` 表示现在。
        """

        now = self._now(moment)
        self._inbound.append(now)
        self._trim(now)

    def note_outbound(self, moment: Optional[datetime] = None) -> None:
        """记录一条我们发出的消息。

        Args:
            moment: 消息时刻；``None`` 表示现在。
        """

        now = self._now(moment)
        self._outbound.append(now)
        self._trim(now)

    def note_complaint(self, moment: Optional[datetime] = None) -> None:
        """记录一次"被嫌弃"事件，进入强制静默。

        触发来源包括群友抱怨刷屏、``/ad`` 举报、投票 ban 等。

        Args:
            moment: 事件时刻；``None`` 表示现在。
        """

        now = self._now(moment)
        self._silent_until = now + timedelta(minutes=self.silence_until_minutes())

    def silence_until_minutes(self) -> float:
        """返回本次静默时长（分钟），带随机浮动。

        Returns:
            float: 静默分钟数。
        """

        jitter = random.uniform(-_SILENCE_JITTER, _SILENCE_JITTER)
        return self._silence_minutes * (1.0 + jitter)

    def current_share(self, moment: Optional[datetime] = None) -> Optional[float]:
        """返回当前窗口内我们的话量占比。

        Args:
            moment: 计算时刻；``None`` 表示现在。

        Returns:
            Optional[float]: 占比；样本不足时返回 ``None``。
        """

        now = self._now(moment)
        self._trim(now)
        total = len(self._inbound) + len(self._outbound)
        if total < self._min_samples:
            return None
        return len(self._outbound) / total

    def allows_send(self, moment: Optional[datetime] = None) -> bool:
        """判断此刻是否允许发言。

        Args:
            moment: 判定时刻；``None`` 表示现在。

        Returns:
            bool: 允许发言返回 ``True``。
        """

        now = self._now(moment)

        if self._silent_until is not None:
            if now < self._silent_until:
                return False
            self._silent_until = None

        share = self.current_share(now)
        if share is None:
            # 样本不足：冷群保护，不判定
            return True
        return share <= self._max_share

    def describe_block(self, moment: Optional[datetime] = None) -> Optional[str]:
        """返回被拦截的原因描述，用于日志排障。

        Args:
            moment: 判定时刻；``None`` 表示现在。

        Returns:
            Optional[str]: 被拦时返回原因，允许发言时返回 ``None``。
        """

        now = self._now(moment)

        if self._silent_until is not None and now < self._silent_until:
            remain = (self._silent_until - now).total_seconds() / 60
            return f"被投诉后静默中，剩余 {remain:.0f} 分钟"

        share = self.current_share(now)
        if share is not None and share > self._max_share:
            total = len(self._inbound) + len(self._outbound)
            return (
                f"话语权占比过高: {share * 100:.0f}% "
                f"({len(self._outbound)}/{total} 条) "
                f"上限 {self._max_share * 100:.0f}%"
            )
        return None
