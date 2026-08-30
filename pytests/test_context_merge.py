"""高频群上下文整理测试。

用例取自 5 万人技术群的**真实消息序列**（某大型技术群，
1200 条采样），而非构造场景。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

import pytest

from src.services.context_merge import merge_consecutive_messages


@dataclass
class _UserInfo:
    user_id: str
    user_nickname: str = ""
    user_cardname: Optional[str] = None
    is_bot: bool = False


@dataclass
class _MsgInfo:
    user_info: _UserInfo


@dataclass
class _Msg:
    """最小化的 SessionMessage 替身。"""

    user_id: str
    processed_plain_text: str
    offset_seconds: float
    message_info: _MsgInfo = field(init=False)
    timestamp: datetime = field(init=False)

    _BASE = datetime(2026, 8, 31, 18, 0, 0)

    def __post_init__(self) -> None:
        self.message_info = _MsgInfo(_UserInfo(self.user_id, f"user{self.user_id}"))
        self.timestamp = self._BASE + timedelta(seconds=self.offset_seconds)


def _texts(messages: List[_Msg]) -> List[str]:
    return [m.processed_plain_text for m in messages]


def test_merges_uninterrupted_consecutive_messages() -> None:
    """同一人连发且无人插队时应合并。

    真实样本：辣子鸡 18:08:17 "睡觉了" / 18:08:18 "晚安"
    """

    merged = merge_consecutive_messages(
        [_Msg("A", "睡觉了", 0), _Msg("A", "晚安", 1)]
    )

    assert _texts(merged) == ["睡觉了 晚安"]


def test_merges_across_interleaved_other_speaker() -> None:
    """被他人插队打断的连续发言仍应合并。

    这是本模块的核心目的。真实样本（辣子鸡 18:12:18~18:12:51）：
    节点链接 / 节点已更新 / 没有 / 域名挂了……中间夹杂他人发言。
    """

    merged = merge_consecutive_messages(
        [
            _Msg("A", "节点已更新", 0),
            _Msg("B", "今天全红有和我一样的吗", 5),
            _Msg("A", "没有", 10),
            _Msg("A", "域名挂了换一个二级", 20),
        ]
    )

    assert _texts(merged) == ["节点已更新 没有 域名挂了换一个二级", "今天全红有和我一样的吗"]


def test_preserves_first_message_timestamp_order() -> None:
    """合并后按段落起点排序，保持对话时间脉络。"""

    merged = merge_consecutive_messages(
        [
            _Msg("A", "第一句", 0),
            _Msg("B", "插一句", 3),
            _Msg("A", "第二句", 6),
        ]
    )

    assert merged[0].message_info.user_info.user_id == "A"
    assert merged[0].timestamp == _Msg._BASE
    assert merged[1].message_info.user_info.user_id == "B"


def test_does_not_merge_beyond_time_window() -> None:
    """超出时间窗视为两段话，不合并。

    实测 P90=26s，30s 窗外多半已是新话题。
    """

    merged = merge_consecutive_messages(
        [_Msg("A", "早上好", 0), _Msg("A", "晚上好", 120)],
        window_seconds=30.0,
    )

    assert _texts(merged) == ["早上好", "晚上好"]


def test_does_not_merge_beyond_interleave_limit() -> None:
    """插入过多他人消息时不再合并，避免跨话题粘连。"""

    messages: List[_Msg] = [_Msg("A", "开头", 0)]
    messages.extend(_Msg(f"U{i}", f"路人{i}", 1 + i) for i in range(10))
    messages.append(_Msg("A", "结尾", 12))

    merged = merge_consecutive_messages(messages, max_interleave=8)

    assert "开头 结尾" not in _texts(merged), "插入过多仍合并，会把不同话题粘在一起"


def test_multiple_speakers_merge_independently() -> None:
    """多人交替连发时，各自的段落应分别合并。

    真实样本：Aio 与 辣子鸡 在 18:11~18:15 交替连发。
    """

    merged = merge_consecutive_messages(
        [
            _Msg("Aio", "今天全红", 0),
            _Msg("LZJ", "节点已更新", 2),
            _Msg("Aio", "workers那都是红的", 4),
            _Msg("LZJ", "没有", 6),
            _Msg("Aio", "这是什么原因", 8),
        ]
    )

    assert _texts(merged) == ["今天全红 workers那都是红的 这是什么原因", "节点已更新 没有"]


def test_short_replies_are_merged() -> None:
    """≤4 字的短消息占 17%，最容易被拆散，必须能合并。"""

    merged = merge_consecutive_messages(
        [_Msg("A", "？", 0), _Msg("B", "咋了", 2), _Msg("A", "没事", 4)]
    )

    assert _texts(merged)[0] == "？ 没事"


def test_empty_and_single_input_are_safe() -> None:
    """空列表与单条输入不应报错。"""

    assert merge_consecutive_messages([]) == []
    single = [_Msg("A", "只有一条", 0)]
    assert _texts(merge_consecutive_messages(single)) == ["只有一条"]


def test_messages_without_text_are_preserved() -> None:
    """无正文消息（纯媒体）原样保留，不参与合并。"""

    merged = merge_consecutive_messages(
        [_Msg("A", "看这个", 0), _Msg("A", "", 1), _Msg("A", "好看吧", 2)]
    )

    assert len(merged) == 2, "空正文消息应被保留为独立条目"
    assert "看这个 好看吧" in _texts(merged)


def test_malformed_messages_do_not_crash() -> None:
    """结构不完整的消息应原样保留而不是抛异常。"""

    class _Broken:
        processed_plain_text = "坏消息"

    merged = merge_consecutive_messages([_Broken(), _Msg("A", "正常", 1)])

    assert len(merged) == 2
