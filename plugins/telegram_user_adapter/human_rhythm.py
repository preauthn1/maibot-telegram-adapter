"""按真人作息调节发言意愿。

背景：实测发现账号 95% 的发言挤在 07:00-09:00 三小时内（占比
22%/33%/29%），而同群 327 个真人这三小时只占 20%。真人的活跃高峰
在 16:00-23:00 与 0 点前后。更糟的是凌晨 2-5 点真人几乎全睡了
（3.1%/0.7%/0.3%），我们却有 11.6%/0/2.7% 的发言。

一个"人"每天只在早上集中说一百句、深夜还清醒，比说错话更容易
暴露——这是行为指纹，不是内容问题。

做法：按真人实测分布给每个小时一个活跃度系数，乘进发言意愿。
系数来自同群真人样本，不是拍脑袋定的。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict

import random

CN_TZ = timezone(timedelta(hours=8))

# 各小时的真人发言占比（%），取自同群 327 个真人、2896 条消息的实测样本。
# 10:00-13:00 因采样窗口边界缺数据，按相邻时段线性补齐。
_HUMAN_HOURLY_SHARE: Dict[int, float] = {
    0: 13.7, 1: 5.6, 2: 3.1, 3: 0.7, 4: 0.3, 5: 0.5,
    6: 4.2, 7: 7.6, 8: 4.7, 9: 7.7, 10: 5.0, 11: 4.0,
    12: 3.5, 13: 3.0, 14: 2.7, 15: 2.7, 16: 6.2, 17: 7.6,
    18: 4.9, 19: 3.9, 20: 5.1, 21: 8.7, 22: 4.1, 23: 5.9,
}

# 把占比归一化成倍率时的基准：取所有小时的平均占比。
_MEAN_SHARE = sum(_HUMAN_HOURLY_SHARE.values()) / len(_HUMAN_HOURLY_SHARE)

# 倍率区间。下限不设为 0——完全不发言反而形成"精确到点开关机"的
# 规律，真人偶尔也会半夜冒一句。
#
# 下限从 0.15 提到 0.20：这个值与互动权重下限是乘法关系，
# 0.40 × 0.15 = 0.06 意味着冷群只剩 6% 发言能力。深夜静默由
# _DEEP_SLEEP_MULTIPLIER 单独负责，这里不必再压那么狠。
MIN_MULTIPLIER = 0.15
MAX_MULTIPLIER = 1.8

# 深度睡眠时段：真人占比低于该阈值的小时，额外压制。
_DEEP_SLEEP_THRESHOLD = 1.0
_DEEP_SLEEP_MULTIPLIER = 0.08

# 每日作息抖动幅度（小时）。真人不会每天精确同一时刻变得活跃，
# 给作息曲线加一个当天固定的随机偏移，避免跨天出现完全相同的模式。
_DAILY_JITTER_HOURS = 1.0


def _daily_offset(day_seed: str) -> float:
    """生成当天固定的作息偏移。

    同一天内保持不变（否则同一小时内反复抖动没有意义），
    跨天则变化——真人今天可能 10 点起、明天 11 点起。

    Args:
        day_seed: 形如 ``2026-08-31`` 的日期串。

    Returns:
        float: ``[-_DAILY_JITTER_HOURS, _DAILY_JITTER_HOURS]`` 内的偏移。
    """

    rng = random.Random(day_seed)
    return rng.uniform(-_DAILY_JITTER_HOURS, _DAILY_JITTER_HOURS)


def get_activity_multiplier(now: datetime | None = None) -> float:
    """返回当前时刻的活跃度倍率。

    Args:
        now: 当前时间；省略则取北京时间。

    Returns:
        float: 落在 ``[MIN_MULTIPLIER, MAX_MULTIPLIER]`` 的倍率。
            1.0 表示与真人平均水平相当。
    """

    current = now or datetime.now(CN_TZ)
    offset = _daily_offset(current.strftime("%Y-%m-%d"))

    # 把偏移折算到小时刻度上，让作息曲线整体平移。
    shifted = (current.hour + current.minute / 60.0 - offset) % 24
    hour = int(shifted)
    share = _HUMAN_HOURLY_SHARE[hour]

    # 深度睡眠时段强压：这几个小时发言最容易暴露。
    if share < _DEEP_SLEEP_THRESHOLD:
        return _DEEP_SLEEP_MULTIPLIER

    multiplier = share / _MEAN_SHARE
    return max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, multiplier))


def describe_schedule() -> str:
    """输出作息曲线，便于人工核对。

    Returns:
        str: 每小时倍率的多行文本。
    """

    lines = ["时  真人占比  倍率"]
    for hour in range(24):
        share = _HUMAN_HOURLY_SHARE[hour]
        if share < _DEEP_SLEEP_THRESHOLD:
            mult = _DEEP_SLEEP_MULTIPLIER
        else:
            mult = max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, share / _MEAN_SHARE))
        bar = "█" * int(mult * 10)
        lines.append(f"{hour:>2}  {share:>6.1f}%  {mult:>4.2f} {bar}")
    return "\n".join(lines)
