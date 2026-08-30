"""高频群聊上下文整理。

问题（实测于 5 万人技术群，3.7 条/分钟）：同一个人连着发的几条消息，
会被其他人的消息插在中间拆散。模型看到的是：

    辣子鸡说：节点已更新
    Aio说：今天全红
    辣子鸡说：没有
    辣子鸡说：域名挂了换一个二级

"节点已更新 / 没有 / 域名挂了" 本是一口气说完的一段话，被拆开后
每条都像在回应不同的人，模型据此理解必然错乱。

实测数据（1200 条样本，1183 条真人消息）：

- 同一人相邻消息间隔 P50=9s、P75=16s、P90=26s
- 30s 窗口可覆盖 92% 的连续消息对
- 「A→B→A 且 A 两条相隔≤30s」的被打断情形有 152 处
- 两条同人消息之间最多插入 7 条他人消息
- 只有 29% 的消息带 reply_to，无法靠回复链还原归属
- 17% 是 ≤4 字的短消息（"？""没有""晚安"），最容易被拆散

因此采用「跨插队合并」：把窗口内同一发送者的消息合并成一条，
即使中间隔着别人的消息。合并后仍按**首条消息的时间**排序，
保持对话的时间脉络。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# 合并窗口。取 30s：覆盖 92% 的连续消息，且短于常见的话题切换间隔。
# 放大到 60s 只多覆盖 7%，却会把两个不同话题的发言错误粘在一起。
DEFAULT_MERGE_WINDOW_SECONDS = 30.0

# 允许跨越的他人消息条数上限。实测最多插入 7 条，取 8 留出余量。
# 不设上限的话，低频时段两条相隔很远的消息会被错误合并。
DEFAULT_MAX_INTERLEAVE = 8

# 合并后各片段之间的分隔符。用空格而非换行：
# 这些本来就是一句话拆成几条发的，读起来应当连贯。
_SEGMENT_JOINER = " "


def _sender_key(message: Any) -> Optional[str]:
    """提取消息发送者标识。

    Args:
        message: ``SessionMessage`` 或结构相同的对象。

    Returns:
        Optional[str]: 发送者 ID；结构不完整时返回 ``None``。
    """

    info = getattr(message, "message_info", None)
    user_info = getattr(info, "user_info", None) if info is not None else None
    user_id = getattr(user_info, "user_id", None) if user_info is not None else None
    return str(user_id) if user_id is not None else None


def _timestamp_of(message: Any) -> Optional[float]:
    """提取消息时间戳（秒）。

    Args:
        message: ``SessionMessage`` 或结构相同的对象。

    Returns:
        Optional[float]: Unix 时间戳；无法解析时返回 ``None``。
    """

    raw = getattr(message, "timestamp", None)
    if raw is None:
        return None
    to_ts = getattr(raw, "timestamp", None)
    if callable(to_ts):
        try:
            return float(to_ts())
        except (TypeError, ValueError, OSError):
            return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def merge_consecutive_messages(
    messages: List[Any],
    *,
    window_seconds: float = DEFAULT_MERGE_WINDOW_SECONDS,
    max_interleave: int = DEFAULT_MAX_INTERLEAVE,
) -> List[Any]:
    """合并被他人插队打断的同一发送者连续消息。

    合并后的消息保留**首条**的全部字段（时间戳、message_id 等），
    只把后续片段的正文追加到 ``processed_plain_text``。
    这样排序与引用关系都以段落起点为准，符合"这是一段话"的语义。

    Args:
        messages: 时间正序的消息列表。
        window_seconds: 合并时间窗，超出则视为新的一段话。
        max_interleave: 两个片段之间允许插入的他人消息条数上限。

    Returns:
        List[Any]: 合并后的消息列表，仍为时间正序。
    """

    if len(messages) < 2:
        return list(messages)

    # 每个发送者当前"开放"的段落：sender -> (结果列表下标, 最后片段时间, 已插入他人条数)
    open_segments: Dict[str, Tuple[int, float, int]] = {}
    merged: List[Any] = []
    # 记录每条结果消息追加的正文，最后统一写回，避免中途改动影响判断。
    appended: Dict[int, List[str]] = {}

    for message in messages:
        sender = _sender_key(message)
        ts = _timestamp_of(message)
        text = (getattr(message, "processed_plain_text", "") or "").strip()

        # 结构不完整或无正文的消息不参与合并，原样保留。
        if sender is None or ts is None or not text:
            merged.append(message)
            for key, (idx, last_ts, gap) in list(open_segments.items()):
                open_segments[key] = (idx, last_ts, gap + 1)
            continue

        opened = open_segments.get(sender)
        if (
            opened is not None
            and ts - opened[1] <= window_seconds
            and opened[2] <= max_interleave
        ):
            # 归入该发送者已开放的段落。
            appended.setdefault(opened[0], []).append(text)
            open_segments[sender] = (opened[0], ts, opened[2])
        else:
            merged.append(message)
            open_segments[sender] = (len(merged) - 1, ts, 0)

        # 本条消息对其他发送者而言就是一次"插队"。
        for key, (idx, last_ts, gap) in list(open_segments.items()):
            if key != sender:
                open_segments[key] = (idx, last_ts, gap + 1)

    # 统一写回合并后的正文。
    for idx, extra_parts in appended.items():
        target = merged[idx]
        base = (getattr(target, "processed_plain_text", "") or "").strip()
        combined = _SEGMENT_JOINER.join([base, *extra_parts])
        try:
            target.processed_plain_text = combined
        except AttributeError:
            # 只读对象无法合并时保持原样，不影响主流程。
            continue

    return merged
