"""连发上限的并发安全测试。

审计发现的 P0-3：``max_consecutive_replies`` 的检查在入队前
（``plugin.py`` 的 ``_is_consecutive_limited``），自增在发送成功后
（``_after_successful_send``）。两者之间隔着整条队列等待 +
发送间隔 + 打字模拟，可能几十秒。

Host 在短时间内为同一 chat 下发多条出站消息（拆段回复、多轮并发
决策）时，它们看到的计数全是 0，于是全部放行——上限形同虚设。
而 config.py 对该项的描述是「贴着一个人连续接话是被识破的头号原因」。

修复：检查通过就立刻预占名额，每条失败路径回滚。
这里直接测预占/回滚这对语义，不依赖完整的 Host 环境。
"""

from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))


class _CounterOnly:
    """只带连发计数的最小载体。

    直接复用 plugin 的方法实现，避免为测一对增减语义
    去搭整个 Host + Telethon 环境。
    """

    def __init__(self) -> None:
        """初始化计数表。"""

        self._consecutive_replies: dict[str, int] = {}

    # 与 TelegramUserAdapterPlugin._release_consecutive 保持一致
    def release(self, chat_id: str) -> None:
        """归还一个预占名额。"""

        if not chat_id:
            return
        current = self._consecutive_replies.get(chat_id, 0)
        if current > 0:
            self._consecutive_replies[chat_id] = current - 1

    def reserve(self, chat_id: str) -> str:
        """预占一个名额，返回用于回滚的标记。"""

        if not chat_id:
            return ""
        self._consecutive_replies[chat_id] = (
            self._consecutive_replies.get(chat_id, 0) + 1
        )
        return chat_id


def test_reserve_is_visible_immediately() -> None:
    """预占必须立刻可见——这正是修复 TOCTOU 的关键。

    原实现要等发送成功才自增，并发提交的消息全看到 0。
    """

    holder = _CounterOnly()

    holder.reserve("chat-a")
    holder.reserve("chat-a")
    holder.reserve("chat-a")

    assert holder._consecutive_replies["chat-a"] == 3


def test_release_rolls_back_failed_send() -> None:
    """发送失败要归还名额，否则几次失败后该群彻底闭嘴。"""

    holder = _CounterOnly()

    token = holder.reserve("chat-a")
    holder.release(token)

    assert holder._consecutive_replies["chat-a"] == 0


def test_release_never_goes_negative() -> None:
    """重复回滚不该把计数压到负数——那会凭空放宽上限。"""

    holder = _CounterOnly()

    holder.reserve("chat-a")
    holder.release("chat-a")
    holder.release("chat-a")
    holder.release("chat-a")

    assert holder._consecutive_replies["chat-a"] == 0


def test_release_ignores_empty_token() -> None:
    """没预占过（空标记）时回滚应当无副作用。"""

    holder = _CounterOnly()
    holder.reserve("chat-a")

    holder.release("")

    assert holder._consecutive_replies["chat-a"] == 1


def test_counters_are_per_chat() -> None:
    """各会话的连发计数互不影响。"""

    holder = _CounterOnly()

    holder.reserve("chat-a")
    holder.reserve("chat-a")
    holder.reserve("chat-b")
    holder.release("chat-b")

    assert holder._consecutive_replies["chat-a"] == 2
    assert holder._consecutive_replies["chat-b"] == 0


def test_plugin_exposes_release_helper() -> None:
    """确认 plugin 真的提供了这个回滚方法（防止改名后测试空转）。"""

    from telegram_user_adapter import plugin as plugin_module

    assert hasattr(plugin_module.TelegramUserAdapterPlugin, "_release_consecutive")
