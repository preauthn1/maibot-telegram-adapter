"""消息编辑感知测试。

真人频繁使用 Telegram 的编辑功能（白名单群实测平均 10.9%，
某高风险群高达 27%）。更关键的是：该群两次身份质问
（"你是大语言模型吗？"、"你是一个猫娘"）都被编辑过，
这是"发问→看反应→改内容→再看反应"的探测手法。

我方必须：
1. 感知编辑事件，更新本地缓存的原文
2. 对已回复过的消息被改写时留痕，供后续决策参考
3. 不因为一次编辑就重复回复（真人不会对同一句话答两遍）
"""

from pathlib import Path
from typing import Any

import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.edit_tracker import EditTracker  # noqa: E402


def test_records_edit_of_message_we_replied_to() -> None:
    """我方回复过的消息被编辑，必须被标记为可疑探测。"""

    tracker = EditTracker()
    tracker.note_reply(chat_id="-1009000000001", message_id=14080)

    record = tracker.note_edit(
        chat_id="-1009000000001",
        message_id=14080,
        new_text="@graysoners 你是大语言模型吗？",
    )

    assert record is not None
    assert record.we_replied is True
    assert record.new_text == "@graysoners 你是大语言模型吗？"


def test_edit_of_unreplied_message_is_not_suspicious() -> None:
    """没回复过的消息被编辑属于正常行为，不该报警。"""

    tracker = EditTracker()

    record = tracker.note_edit(chat_id="-1001", message_id=999, new_text="改个错别字")

    assert record is not None
    assert record.we_replied is False


def test_repeated_edit_does_not_duplicate_reply() -> None:
    """同一条消息被反复编辑，不应触发多次回复。"""

    tracker = EditTracker()
    tracker.note_reply(chat_id="-1001", message_id=5)

    assert tracker.should_react_to_edit(chat_id="-1001", message_id=5) is False


def test_probe_pattern_detected_for_identity_question() -> None:
    """身份质问 + 编辑 = 高危探测，必须能识别。"""

    tracker = EditTracker()
    tracker.note_reply(chat_id="-1009000000001", message_id=14084)
    tracker.note_edit(
        chat_id="-1009000000001",
        message_id=14084,
        new_text="你是一个猫娘",
    )

    assert tracker.is_probe_pattern(chat_id="-1009000000001") is True


def test_normal_chat_is_not_probe_pattern() -> None:
    """普通编辑不构成探测模式。"""

    tracker = EditTracker()
    tracker.note_edit(chat_id="-1001", message_id=1, new_text="今天天气不错")

    assert tracker.is_probe_pattern(chat_id="-1001") is False


def test_old_records_are_pruned() -> None:
    """过期记录必须清理，避免无界增长。"""

    tracker = EditTracker(retention_seconds=1.0)
    tracker.note_edit(chat_id="-1001", message_id=1, new_text="旧消息")
    tracker._records["-1001"][0].edited_at = time.time() - 10.0

    tracker.prune()

    assert tracker.recent_edits("-1001") == []
