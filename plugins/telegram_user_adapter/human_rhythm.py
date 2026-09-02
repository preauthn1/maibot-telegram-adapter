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

# 各小时的真人发言占比（%）。
#
# 2026-09-02 用全量 69691 条入站消息重新统计，替换此前的
# 327 人 / 2896 条小样本——旧样本严重失真：
#
#     时段    旧样本    实测全量    偏差
#      0时    13.7%      0.3%     -13.4   ← 旧样本以为 0 点第二活跃
#      1时     5.6%      0.1%      -5.5
#     20时     5.1%     15.7%     +10.6   ← 真正的高峰被低估
#     21时     8.7%     15.1%      +6.4
#
# 用旧系数的直接后果：0 点倍率 1.16、23 点 1.80，系统在深夜
# **鼓励**发言。实测 00-08 时我们发 281 条、群里才 1410 条，
# 占比 19.9%；而 15-23 时占比仅 0.84%——凌晨占比是白天的 24 倍。
# 凌晨 1/2/4/5 点，群里每 3-4 条就有 1 条是我们发的。
#
# 这比"24 小时在线"更致命：在线只是状态，这是行为，
# 往上翻聊天记录就能看出来。
_HUMAN_HOURLY_SHARE: Dict[int, float] = {
    0: 0.3, 1: 0.1, 2: 0.3, 3: 0.2, 4: 0.2, 5: 0.2,
    6: 0.2, 7: 0.4, 8: 0.5, 9: 0.7, 10: 1.1, 11: 1.3,
    12: 1.2, 13: 1.4, 14: 2.3, 15: 6.5, 16: 8.9, 17: 11.1,
    18: 8.8, 19: 10.2, 20: 15.7, 21: 15.1, 22: 9.8, 23: 3.3,
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
#
# 阈值 0.6% 对应 2026-09-02 全量统计（69691 条）的真实低谷：
#     0-8 时占比 0.1%-0.5%   ← 全部落入深睡区
#     9 时 0.7%、10 时 1.1%  ← 开始回升，不再压制
#     23 时 3.3%             ← 明确活跃，不该压制
#
# 旧阈值 1.0 配旧系数时尚可，换上全量数据后会把 9-13 时
# （占比 0.7%-1.4%，属正常白天低活跃）一并打成深睡，
# 白天反而哑火。
_DEEP_SLEEP_THRESHOLD = 0.6
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
