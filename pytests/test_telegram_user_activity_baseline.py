"""无 @ 互动时的基线倍率测试。

实测所有群权重恒为 0.77 = MIN_MULTIPLIER(0.6) × 作息(1.289)，
BASE_MULTIPLIER 完全走不到。根因：compute_multiplier 开头
`if not events: return self._min`，而 record_engagement 只在
被 @ 或被回复时调用 —— 日常群聊没人 @ 我们，events 恒空。

结果是"没人 @ 就一直沉默"，正是该群周期性不说话的原因。
用户要的 talk_value 1.3~1.5 必须在"无人 @ 但群在聊"这个常态下生效。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter import engagement as eng  # noqa: E402
from telegram_user_adapter.engagement import ChatEngagementTracker  # noqa: E402


def test_active_chat_without_mention_reaches_base() -> None:
    """群里有人说话但没 @ 我们时，倍率应达到基准而非最低值。"""

    tracker = ChatEngagementTracker()
    chat = "-1009000000011"

    for index in range(6):
        tracker.record_activity(chat, f"user{index}")

    multiplier = tracker.compute_multiplier(chat)

    assert multiplier >= 1.0, f"活跃群倍率仅 {multiplier:.2f}，仍被压在基线以下"


def test_truly_silent_chat_stays_at_minimum() -> None:
    """完全没有任何消息的群保持最低倍率。"""

    tracker = ChatEngagementTracker()

    assert tracker.compute_multiplier("-1009000000012") == eng.MIN_MULTIPLIER


def test_mention_outweighs_plain_activity() -> None:
    """被 @ 仍应比单纯有人说话权重更高。"""

    tracker = ChatEngagementTracker()
    plain = "-1009000000013"
    mentioned = "-1009000000014"

    for index in range(6):
        tracker.record_activity(plain, f"user{index}")
    for index in range(6):
        tracker.record_engagement(mentioned, f"user{index}")

    assert tracker.compute_multiplier(mentioned) > tracker.compute_multiplier(plain)


def test_single_user_activity_flood_capped() -> None:
    """一个人自言自语撑不起群权重，防刷 token。"""

    tracker = ChatEngagementTracker()
    solo = "-1009000000015"
    diverse = "-1009000000016"

    for _ in range(30):
        tracker.record_activity(solo, "chatty")
    for index in range(6):
        tracker.record_activity(diverse, f"user{index}")

    assert tracker.compute_multiplier(solo) < tracker.compute_multiplier(diverse)
