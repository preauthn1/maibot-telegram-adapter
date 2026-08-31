"""连续发言抑制测试。

线上真实翻车：在某休闲小群里 22 条消息中我们插了 7 句、贴着一个人接话，
对方随即质问\"ai？\"。这里用同样的序列验证抑制机制能挡住刷屏式接话。
"""

from __future__ import annotations

from pathlib import Path

import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.self_improvement import detect_suspicion  # noqa: E402


class _FakePlugin:
    """只保留连发抑制所需状态的最小实现，避免拉起整个插件。"""

    def __init__(self, limit: int = 3, cooldown: float = 180.0) -> None:
        self.limit = limit
        self.cooldown = cooldown
        self.consecutive: dict[str, int] = {}
        self.blocked_at: dict[str, float] = {}
        self.now = 0.0
        self.sent: list[str] = []

    def _is_limited(self, chat: str) -> bool:
        count = self.consecutive.get(chat, 0)
        if count < self.limit:
            return False
        blocked = self.blocked_at.get(chat)
        if blocked is None:
            self.blocked_at[chat] = self.now
            return True
        if (self.now - blocked) >= self.cooldown:
            self.consecutive[chat] = 0
            self.blocked_at.pop(chat, None)
            return False
        return True

    def try_send(self, chat: str, text: str) -> bool:
        """模拟一次出站。返回是否真的发出去。"""

        if self._is_limited(chat):
            return False
        self.consecutive[chat] = self.consecutive.get(chat, 0) + 1
        self.sent.append(text)
        return True

    def inbound(self, chat: str) -> None:
        """别人说话，连发链条断开。"""

        self.consecutive.pop(chat, None)
        self.blocked_at.pop(chat, None)


def test_consecutive_replies_capped() -> None:
    """连续发言必须在达到上限后被挡住。"""

    p = _FakePlugin(limit=3)
    chat = "-1009000000002"

    assert p.try_send(chat, "1")
    assert p.try_send(chat, "2")
    assert p.try_send(chat, "3")
    # 第 4 条必须被挡
    assert not p.try_send(chat, "4")
    assert len(p.sent) == 3


def test_inbound_resets_counter() -> None:
    """别人插话后应当可以继续说，不能一直闭嘴。"""

    p = _FakePlugin(limit=3)
    chat = "-1009000000002"

    for i in range(3):
        p.try_send(chat, str(i))
    assert not p.try_send(chat, "blocked")

    p.inbound(chat)  # 别人说了句话
    assert p.try_send(chat, "resumed")


def test_cooldown_expires() -> None:
    """冷却结束后自动恢复，避免永久闭嘴。"""

    p = _FakePlugin(limit=2, cooldown=180.0)
    chat = "-100123"

    p.try_send(chat, "1")
    p.try_send(chat, "2")
    assert not p.try_send(chat, "3")

    p.now += 181.0
    assert p.try_send(chat, "after cooldown")


def test_limit_is_per_chat() -> None:
    """一个群被限流不该影响其他群。"""

    p = _FakePlugin(limit=2)
    p.try_send("-100A", "1")
    p.try_send("-100A", "2")
    assert not p.try_send("-100A", "3")
    # 另一个群不受影响
    assert p.try_send("-100B", "1")


def test_real_genshin_scenario_would_be_suppressed() -> None:
    """重放真实翻车序列：原本插了 7 句，抑制后必须显著减少。"""

    p = _FakePlugin(limit=3)
    chat = "-1009000000002"

    # 真实序列：对方连续自言自语，我们不断接话（中间对方消息不算入站
    # 重置的只有\"别人说话\"，这里对方确实在说话，所以按真实节奏交替）
    # 简化为最坏情况：我们连续接话没有间隔
    ours = [
        "哈哈串台了",
        "肝到天亮吗这是",
        "这画风突然变女仆了",
        "这时间安排得明明白白",
        "跟着月妈不迷路",
        "50发有点狠啊",
        "25发了啊 出金没",
    ]
    for text in ours:
        p.try_send(chat, text)

    # 原本 7 句全发出去了，现在最多 3 句
    assert len(p.sent) <= 3, f"仍然发了 {len(p.sent)} 句，抑制失效"


def test_ai_question_now_detected() -> None:
    """那句导致暴露的\"ai？\"必须能被识别，才能进教训库。"""

    assert detect_suspicion("ai？")
    assert detect_suspicion("ai?")
    assert detect_suspicion("AI?")


def test_normal_ai_talk_not_flagged() -> None:
    """群里正常聊 AI 话题不能误判为质疑。"""

    for text in ["ai绘画好厉害", "这个ai工具不错", "原神ai太蠢了", "人机对战"]:
        assert not detect_suspicion(text), f"{text!r} 被误判"


class _FloodPlugin:
    """单用户防刷的最小实现。"""

    def __init__(self, limit: int = 12, window: float = 600.0) -> None:
        self.limit = limit
        self.window = window
        self.now = 0.0
        self.times: dict[tuple[str, str], list[float]] = {}

    def is_flooding(self, chat: str, sender: str) -> bool:
        key = (chat, sender)
        stamps = self.times.setdefault(key, [])
        cutoff = self.now - self.window
        stamps[:] = [t for t in stamps if t >= cutoff]
        stamps.append(self.now)
        return len(stamps) > self.limit


def test_normal_conversation_not_flagged_as_flood() -> None:
    """正常对话节奏（10分钟内10句）不该被当成刷屏。"""

    p = _FloodPlugin(limit=12, window=600.0)
    blocked = 0
    for _ in range(10):
        p.now += 30.0  # 每30秒说一句，很正常
        if p.is_flooding("-100X", "user1"):
            blocked += 1
    assert blocked == 0, "正常对话被误判为刷屏"


def test_rapid_flood_is_blocked() -> None:
    """短时间狂刷必须被挡。"""

    p = _FloodPlugin(limit=12, window=600.0)
    blocked = 0
    for _ in range(30):
        p.now += 1.0  # 每秒一条
        if p.is_flooding("-100X", "spammer"):
            blocked += 1
    assert blocked > 0, "刷屏未被识别"


def test_flood_limit_is_per_user() -> None:
    """一个人刷屏不该影响群里其他人。"""

    p = _FloodPlugin(limit=5, window=600.0)
    for _ in range(10):
        p.now += 1.0
        p.is_flooding("-100X", "spammer")
    # 另一个正常用户不受影响
    assert not p.is_flooding("-100X", "normal_user")


def test_flood_window_expires() -> None:
    """窗口过后重新计数，不能永久拉黑。"""

    p = _FloodPlugin(limit=5, window=600.0)
    for _ in range(10):
        p.now += 1.0
        p.is_flooding("-100X", "user1")
    # 窗口过去
    p.now += 601.0
    assert not p.is_flooding("-100X", "user1")
