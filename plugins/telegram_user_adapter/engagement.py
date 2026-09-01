"""按群互动质量动态调整发言意愿。

问题：所有群共用一个发言频率，导致两种浪费——
- 真在跟我们聊天的群，回复不够积极；
- 纯刷屏或与我们无关的群，照样消耗推理。

做法：为每个会话算一个 ``engagement_multiplier``，写回 Host 现成的
``_talk_frequency_adjust`` 槽位（通过 ``frequency.set_adjust`` 能力）。
一个写入点，下游所有阈值自动继承。

**防刷设计**：倍率不看消息总量，只看\"有多少**不同的人**在跟我们互动\"。
单个人狂刷 @ 无法把权重顶上去——这正是刷 token 的主要手段。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, Tuple

import time

# 统计窗口。与 Host 的外部消息采样窗口（1800s）保持一致。
WINDOW_SECONDS = 1800.0

# 倍率区间。低于 1 表示比默认更沉默，高于 1 表示更积极。
#
# 下限从 0.4 提到 0.6：线上实测 7 次权重写回中 6 次是 0.22，
# 拆解后是 0.40（零互动基线）× 0.562（当时段作息）。两层压制是
# 乘法关系，各自看着合理、相乘后把"没人 @ 我们"的群压到 22%，
# 几乎抵消了参与率上限与退避时长的放宽。
#
# 抬高下限只影响"冷群"的沉默程度，多人互动抬权重、单人刷屏被压
# 这两个区分能力不受影响（见 test_telegram_user_weight_floor）。
#
# 取 0.6（测试锁定区间 0.4~0.6 的上限）：单群场景下并发指纹风险为 0，
# 冷群不必压那么死——真人在自己常驻的群里不会长时间完全不出声。
MIN_MULTIPLIER = 0.6
MAX_MULTIPLIER = 2.0

# 有互动时的基准倍率。
#
# 曾提到 1.4 并当天导致账号被反垃圾系统封禁，但后续实测推翻了归因：
# 真人单群小时峰值最高 80 条、前 10 名平均 68.9 条，1.4 对应的量级
# （单小时 107 条）偏高但同量级。真正的异常是那 107 条散在 12 个会话里，
# 而单小时跨 ≥3 群发言的真人是 0/1128。
#
# 等效路径是同一条乘法链：runtime._get_effective_reply_frequency 返回
# talk_value(≤1) × _talk_frequency_adjust(本模块写回，无上限)。
# 因此调这里等同于调 talk_value 而不触碰 Pydantic 的 le=1 约束。
#
# 取 1.2（测试锁定的区间上限）：当前只有 1 个白名单群，
# 并发会话数维度风险为 0，可以把话量放到真人量级的上沿；
# 并发异常仍由 attention_focus 独立拦截，不依赖本参数。
BASE_MULTIPLIER = 1.2
GAIN = 1.0

# 饱和常数：互动次数达到该量级后收益递减，避免线性膨胀。
SATURATION_K = 5.0

# 多样性分母：至少要有这么多不同的人参与，才能拿满多样性分。
DIVERSITY_TARGET = 3.0

# 衰减半衰期（分钟）：这么久没人互动，权重减半。
DECAY_HALFLIFE_MINUTES = 30.0

# 单个用户在窗口内最多计入多少次互动，防止一人刷高权重。
PER_USER_CAP = 5

# 普通群聊活动相对"被 @"的权重折扣。
#
# 被 @ / 被回复是最强的"该我说话"信号，计 1.0；群里单纯有人聊天
# 说明场子是热的，值得比死群积极，但不该等同于被指名，故打 0.35 折。
#
# 没有这一项时，compute_multiplier 的 `if not events: return self._min`
# 会让所有"无人 @"的群恒定停在最低倍率——线上实测 8 个群权重
# 全是 0.77，这正是账号在活跃群里长时间潜水的原因。
ACTIVITY_WEIGHT = 0.20


class ChatEngagementTracker:
    """跟踪各会话的互动质量并给出发言频率倍率。"""

    def __init__(
        self,
        *,
        window_seconds: float = WINDOW_SECONDS,
        min_multiplier: float = MIN_MULTIPLIER,
        max_multiplier: float = MAX_MULTIPLIER,
    ) -> None:
        """初始化。

        Args:
            window_seconds: 统计窗口长度。
            min_multiplier: 倍率下限。
            max_multiplier: 倍率上限。
        """

        self._window = window_seconds
        self._min = min_multiplier
        self._max = max_multiplier
        # chat_id -> [(时间戳, 用户ID), ...]
        self._events: Dict[str, Deque[Tuple[float, str]]] = {}
        # chat_id -> 最近一次真实互动的时间
        self._last_engagement: Dict[str, float] = {}
        # chat_id -> 上次写回 Host 的倍率，避免重复写入
        self._applied: Dict[str, float] = {}
        # chat_id -> 普通群聊活动（没 @ 我们，但群在聊天）
        self._activity: Dict[str, deque[Tuple[float, str]]] = {}

    def record_engagement(self, chat_id: str, user_id: str) -> None:
        """记录一次真实互动（被 @、被回复、或有人接我们的话）。

        Args:
            chat_id: 会话 ID。
            user_id: 互动者 ID。
        """

        if not chat_id or not user_id:
            return

        now = time.monotonic()
        events = self._events.setdefault(chat_id, deque())
        events.append((now, user_id))
        self._last_engagement[chat_id] = now
        self._prune(chat_id, now)

    def record_activity(self, chat_id: str, user_id: str) -> None:
        """记录一次普通群聊活动（有人说话，但没 @ 我们）。

        原实现只在被 @ / 被回复时记 ``record_engagement``，于是
        ``compute_multiplier`` 里 ``if not events: return self._min``
        让"没人 @ 我们"的群恒定停在最低倍率——线上实测 8 个群
        权重全是 0.77，BASE_MULTIPLIER 根本走不到，表现就是
        群里聊得热火朝天而账号一直潜水。

        普通活动的权重低于被 @（见 ``ACTIVITY_WEIGHT``）：
        群里有人说话说明"场子是热的"，值得比死群更积极，
        但仍不如有人指名找我们。

        Args:
            chat_id: 会话 ID。
            user_id: 发言者 ID。
        """

        if not chat_id or not user_id:
            return

        now = time.monotonic()
        activity = self._activity.setdefault(chat_id, deque())
        activity.append((now, user_id))
        self._prune_activity(chat_id, now)

    def _prune_activity(self, chat_id: str, now: float) -> None:
        """丢弃窗口外的普通活动记录。"""

        activity = self._activity.get(chat_id)
        if activity is None:
            return
        cutoff = now - self._window
        while activity and activity[0][0] < cutoff:
            activity.popleft()

    def _prune(self, chat_id: str, now: float) -> None:
        """丢弃窗口外的事件，保持内存有界。"""

        events = self._events.get(chat_id)
        if events is None:
            return
        cutoff = now - self._window
        while events and events[0][0] < cutoff:
            events.popleft()

    def compute_multiplier(self, chat_id: str) -> float:
        """计算某会话当前的发言频率倍率。

        被 @ / 被回复（``record_engagement``）权重最高；
        群里单纯有人说话（``record_activity``）按 ``ACTIVITY_WEIGHT``
        折算后计入——否则"没人 @ 我们"的群会恒定停在最低倍率。

        Args:
            chat_id: 会话 ID。

        Returns:
            float: 落在 ``[min_multiplier, max_multiplier]`` 的倍率。
        """

        now = time.monotonic()
        self._prune(chat_id, now)
        self._prune_activity(chat_id, now)
        events = self._events.get(chat_id)
        activity = self._activity.get(chat_id)
        if not events and not activity:
            return self._min

        # 每个用户的计数设上限：一个人刷再多也顶不满权重。
        per_user: Dict[str, float] = {}
        for _, uid in events or ():
            per_user[uid] = min(per_user.get(uid, 0.0) + 1.0, float(PER_USER_CAP))

        # 普通活动按折扣计入，且同样受 per-user 上限约束，
        # 防止一个人自言自语撑起整个群的权重。
        activity_per_user: Dict[str, float] = {}
        for _, uid in activity or ():
            activity_per_user[uid] = min(
                activity_per_user.get(uid, 0.0) + 1.0, float(PER_USER_CAP)
            )
        for uid, count in activity_per_user.items():
            per_user[uid] = min(
                per_user.get(uid, 0.0) + count * ACTIVITY_WEIGHT,
                float(PER_USER_CAP),
            )

        engaged_events = float(sum(per_user.values()))
        distinct_users = float(len(per_user))

        # 饱和曲线：互动越多收益越平缓。
        raw = engaged_events / (engaged_events + SATURATION_K)
        # 多样性：只有一个人在互动时拿不满分，这是核心防刷手段。
        diversity = min(1.0, distinct_users / DIVERSITY_TARGET)

        # 时间衰减：久无互动则回落。被 @ 才刷新衰减基准，
        # 普通活动不刷新——否则一个长期灌水的群会永久保持高权重。
        last = self._last_engagement.get(chat_id, now)
        idle_minutes = max(0.0, (now - last) / 60.0)
        decay = 0.5 ** (idle_minutes / DECAY_HALFLIFE_MINUTES)

        value = BASE_MULTIPLIER + GAIN * raw * diversity * decay
        return max(self._min, min(self._max, value))

    def should_apply(self, chat_id: str, multiplier: float, *, epsilon: float = 0.05) -> bool:
        """判断倍率变化是否值得写回 Host。

        变化很小就不写，避免频繁调用能力接口。

        Args:
            chat_id: 会话 ID。
            multiplier: 新算出的倍率。
            epsilon: 触发写入的最小变化量。

        Returns:
            bool: 需要写回时返回 ``True``。
        """

        previous = self._applied.get(chat_id)
        if previous is None:
            return True
        return abs(multiplier - previous) >= epsilon

    def mark_applied(self, chat_id: str, multiplier: float) -> None:
        """记录已写回的倍率。"""

        self._applied[chat_id] = multiplier

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        """导出各会话当前状态，便于日志与排查。

        Returns:
            Dict[str, Dict[str, Any]]: chat_id -> 指标字典。
        """

        now = time.monotonic()
        result: Dict[str, Dict[str, Any]] = {}
        for chat_id in list(self._events.keys()):
            self._prune(chat_id, now)
            events = self._events.get(chat_id) or deque()
            users = {uid for _, uid in events}
            result[chat_id] = {
                "events": len(events),
                "distinct_users": len(users),
                "multiplier": round(self.compute_multiplier(chat_id), 3),
            }
        return result
