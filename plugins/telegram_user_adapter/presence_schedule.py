"""在线作息调度：决定"此刻是否该在线"。

## 为什么需要这个模块

实测（2026-09-02）：
- 每次调用 Telegram API，服务器把账号标记为在线 **5 分钟**
- ``mark_read`` 对每条入站消息都调一次 ``send_read_acknowledge``
- 该群入站消息中位间隔 **8.7 秒**、99% 的间隔 < 5 分钟
- 结果：全天理论可离线仅 **2.5 小时**，其余 21.5 小时持续在线

原 ``PresenceManager`` 的下线延迟是 4-15 秒，下一条入站消息立刻
把在线续期，等于白做——**代码在努力下线，被自己的正常活动持续覆盖**。

24 小时在线是最难辩解的机器特征：真人有睡眠、通勤、上课。
Telegram 客服/风控看到这个作息可以直接认定 spam，
不需要分析任何消息内容。

## 解耦设计

把「是否该在线」的决策从「发送消息」这个动作里剥离：

- ``PresenceSchedule``（本模块）：纯函数式的作息判定，不碰网络、
  不持有客户端。给它一个时刻，它回答"现在能不能在线""能不能发已读"。
- ``PresenceManager``：只负责执行上报，向本模块查询是否被允许。
- 消息读取链路：发已读之前先问本模块，离线时段直接跳过。

这样作息策略可以单独测试、单独调整，不必碰发送逻辑；
反过来发送逻辑改动也不会意外破坏作息。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

import random

# 账号人设所在时区。
#
# 显式绑定而非依赖系统时区：此前踩过 journalctl 显示北京时间、
# 应用日志是 UTC 的坑，同一时刻在两处显示成不同日期。
_CN_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class PresenceWindow:
    """一个作息时段。

    Attributes:
        start_hour: 起始小时（含），0-23。
        end_hour: 结束小时（不含），0-24。可小于 ``start_hour``
            表示跨零点。
        online: 该时段是否允许在线。
    """

    start_hour: int
    end_hour: int
    online: bool

    def contains(self, hour: int) -> bool:
        """判断某个小时是否落在本时段内。

        Args:
            hour: 待判定的小时数，0-23。

        Returns:
            bool: 落在时段内返回 ``True``。
        """

        if self.start_hour <= self.end_hour:
            return self.start_hour <= hour < self.end_hour
        # 跨零点：例如 23 点到次日 7 点
        return hour >= self.start_hour or hour < self.end_hour


# 默认作息：按群里真实活跃度低谷设定。
#
# 数据来源：69688 条入站消息按北京时间分小时统计（2026-09-02 采样）。
# 日均消息量：
#     20时 5481/h  ← 高峰
#     21时 5252/h
#     17时 3855/h
#     15时 2263/h
#     ...
#      7时  148/h  ← 低谷区起点
#      2时  106/h
#      3时   86/h
#      1时   40/h  ← 谷底
#
# 全天中位 441.5/h，低谷阈值取中位数的 35% = 154.5/h。
# 连续低谷时段恰为 00:00-08:00（8 小时），群里真人也在睡觉。
#
# 为什么必须对齐真实低谷而不是拍脑袋：
# 采样显示我们此前在凌晨 2 点发了 58 条，而全群同小时只有 106 条——
# **群里每 2 条消息就有 1 条是我们的**。在线状态只是"看起来不对"，
# 这种发言分布是"行为上明确异常"，往上翻聊天记录就能看出来。
_DEFAULT_WINDOWS: Sequence[PresenceWindow] = (
    PresenceWindow(start_hour=0, end_hour=8, online=False),
)

# 会话驻留时长范围（秒）。
#
# 原实现是 4-15 秒，实测毫无意义：入站消息中位间隔 8.7 秒，
# 下一条消息的 mark_read 立刻把在线续期。
# 改成分钟级，让驻留真正覆盖一次完整对话，
# 对话结束后才有机会落到真正的离线。
_LINGER_MIN_SECONDS = 90.0
_LINGER_MAX_SECONDS = 420.0


class PresenceSchedule:
    """作息判定器。

    纯函数式：不持有网络客户端，不产生副作用，可独立测试。
    """

    def __init__(
        self,
        *,
        windows: Optional[Sequence[PresenceWindow]] = None,
        linger_min: float = _LINGER_MIN_SECONDS,
        linger_max: float = _LINGER_MAX_SECONDS,
    ) -> None:
        """初始化作息判定器。

        Args:
            windows: 作息时段列表。传 ``None`` 用默认（夜间离线），
                传空列表表示不限制。
            linger_min: 会话驻留最短秒数。
            linger_max: 会话驻留最长秒数。
        """

        self._windows: List[PresenceWindow] = list(
            _DEFAULT_WINDOWS if windows is None else windows
        )
        self._linger_min = linger_min
        self._linger_max = linger_max

    @staticmethod
    def _to_local(moment: Optional[datetime]) -> datetime:
        """把任意时刻规整到账号所在时区。

        **契约**：naive datetime 一律按北京时间（墙上时间）解释。
        调用方若持有 UTC 时间，必须先 ``.replace(tzinfo=timezone.utc)``
        再传入——直接传 ``datetime.utcnow()`` 会让判定整体偏移 8 小时。

        本模块内部所有调用都传 ``None``（取当前时间，带时区），
        naive 分支只服务于测试和外部调用方。

        Args:
            moment: 待转换时刻；``None`` 表示当前时间。

        Returns:
            datetime: 带时区的本地时间。
        """

        if moment is None:
            return datetime.now(_CN_TZ)
        if moment.tzinfo is None:
            # 见上方契约：naive 视为北京时间墙上时间。
            return moment.replace(tzinfo=_CN_TZ)
        return moment.astimezone(_CN_TZ)

    def allows_online(self, moment: Optional[datetime] = None) -> bool:
        """判断此刻是否允许在线。

        Args:
            moment: 待判定时刻；``None`` 表示现在。

        Returns:
            bool: 允许在线返回 ``True``。
        """

        if not self._windows:
            # 没配置任何窗口就不限制：保守默认，
            # 避免配置缺失反而把发送功能卡死。
            return True

        hour = self._to_local(moment).hour
        for window in self._windows:
            if window.contains(hour):
                return window.online
        return True

    def allows_read_receipt(self, moment: Optional[datetime] = None) -> bool:
        """判断此刻是否允许发送已读回执。

        这是解耦的关键：``mark_read`` 每条消息调一次 API，
        每次都把在线状态续期 5 分钟。离线时段必须一并停掉，
        否则作息表形同虚设——账号"应该在睡觉"却在持续发已读。

        Args:
            moment: 待判定时刻；``None`` 表示现在。

        Returns:
            bool: 允许发已读返回 ``True``。
        """

        return self.allows_online(moment)

    def session_linger_seconds(self) -> float:
        """返回本次会话结束后的驻留秒数。

        随机化：固定时长本身就是机器特征。

        Returns:
            float: 驻留秒数。
        """

        return random.uniform(self._linger_min, self._linger_max)

    def describe(self) -> str:
        """返回人类可读的作息描述，用于启动日志。

        Returns:
            str: 作息描述。
        """

        if not self._windows:
            return "无限制"
        parts = [
            f"{w.start_hour:02d}:00-{w.end_hour:02d}:00 "
            f"{'在线' if w.online else '离线'}"
            for w in self._windows
        ]
        return "; ".join(parts)
