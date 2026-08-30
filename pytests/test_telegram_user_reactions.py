"""Telegram 真人账号表情回应（reaction）接入测试。

覆盖两条链路：
1. ``parse_reaction_update``：把 MTProto ``UpdateMessageReactions`` 解析成结构化信息。
2. ``TelegramUserAdapterPlugin._on_reaction_update``：只把\"别人给我的消息点表情\"
   写入上下文，且绝不触发回复。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telethon.tl import types  # noqa: E402

from telegram_user_adapter.codecs.reactions import parse_reaction_update  # noqa: E402
from telegram_user_adapter.plugin import TelegramUserAdapterPlugin  # noqa: E402


# ---------------------------------------------------------------------------
# 解析层
# ---------------------------------------------------------------------------


def _make_reaction_update(
    peer: Any,
    msg_id: int,
    emoticons: List[str],
    reactor_ids: List[int] | None = None,
) -> types.UpdateMessageReactions:
    """构造一条表情回应更新，用于测试。"""

    recent = [
        types.MessagePeerReaction(
            peer_id=types.PeerUser(user_id=uid),
            date=datetime.now(timezone.utc),
            reaction=types.ReactionEmoji(emoticon=emoticons[0]),
        )
        for uid in (reactor_ids or [])
    ]
    return types.UpdateMessageReactions(
        peer=peer,
        msg_id=msg_id,
        reactions=types.MessageReactions(
            results=[
                types.ReactionCount(reaction=types.ReactionEmoji(emoticon=e), count=1)
                for e in emoticons
            ],
            recent_reactions=recent or None,
        ),
    )


def test_parse_reaction_in_supergroup() -> None:
    """超级群的 channel_id 必须归一化成 -100 前缀，才能与入站 chat_id 对上。"""

    update = _make_reaction_update(
        types.PeerChannel(channel_id=9000000004), 999, ["❤"], [12345]
    )
    info = parse_reaction_update(update)

    assert info is not None
    assert info.chat_id == -1009000000004
    assert info.message_id == 999
    assert info.emojis == ["❤"]
    assert info.reactor_ids == ["12345"]


def test_parse_reaction_in_private_chat() -> None:
    """私聊使用正数用户 ID。"""

    update = _make_reaction_update(types.PeerUser(user_id=1000000002), 50, ["👍"])
    info = parse_reaction_update(update)

    assert info is not None
    assert info.chat_id == 1000000002
    assert info.emojis == ["👍"]
    assert info.reactor_ids == []


def test_parse_custom_emoji_uses_placeholder() -> None:
    """自定义表情拿不到语义，只能用占位标注，不能编造含义。"""

    update = types.UpdateMessageReactions(
        peer=types.PeerUser(user_id=1),
        msg_id=2,
        reactions=types.MessageReactions(
            results=[
                types.ReactionCount(
                    reaction=types.ReactionCustomEmoji(document_id=123), count=1
                )
            ]
        ),
    )
    info = parse_reaction_update(update)

    assert info is not None
    assert info.emojis == ["[自定义表情]"]


def test_parse_ignores_non_reaction_update() -> None:
    """非表情更新必须原样忽略。"""

    update = types.UpdateUserTyping(
        user_id=1, action=types.SendMessageTypingAction()
    )
    assert parse_reaction_update(update) is None


# ---------------------------------------------------------------------------
# 插件处理层
# ---------------------------------------------------------------------------


class _StubContextCapability:
    """记录 maisaka.context.append 调用的桩。"""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def append(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return {"success": True}


class _StubProactiveCapability:
    """主动触发桩：一旦被调用即视为测试失败。"""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def trigger(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return {"success": True}


class _StubGateway:
    """入站路由桩：一旦被调用即视为测试失败。"""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def route_message(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(kwargs)
        return {"success": True}


def _build_plugin(receive_reactions: bool = True) -> tuple[
    TelegramUserAdapterPlugin, _StubContextCapability, _StubProactiveCapability, _StubGateway
]:
    """构造一个只装配了测试所需依赖的插件实例。"""

    from types import SimpleNamespace

    from telegram_user_adapter.config import TelegramUserPluginSettings

    plugin = TelegramUserAdapterPlugin()
    settings = TelegramUserPluginSettings()
    settings.behavior.receive_reactions = receive_reactions

    context_cap = _StubContextCapability()
    proactive_cap = _StubProactiveCapability()
    gateway = _StubGateway()

    plugin._plugin_config_instance = settings  # type: ignore[attr-defined]
    plugin._ctx = SimpleNamespace(  # type: ignore[attr-defined]
        logger=SimpleNamespace(
            info=lambda *a, **k: None,
            debug=lambda *a, **k: None,
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
        ),
        maisaka=SimpleNamespace(context=context_cap, proactive=proactive_cap),
        gateway=gateway,
    )
    plugin._self_account_id = "1000000001"
    return plugin, context_cap, proactive_cap, gateway


@pytest.mark.asyncio
async def test_reaction_on_own_message_appends_context_without_replying() -> None:
    """别人给我的消息点表情：只进上下文，绝不触发回复或主动发言。"""

    plugin, context_cap, proactive_cap, gateway = _build_plugin()
    plugin._sent_messages[(-1009000000004, 999)] = ("-1009000000004", "今天这个方案我觉得可行")

    update = _make_reaction_update(
        types.PeerChannel(channel_id=9000000004), 999, ["❤"], [12345]
    )
    await plugin._on_reaction_update(update)

    # 上下文被写入一条
    assert len(context_cap.calls) == 1
    call = context_cap.calls[0]
    assert call["stream_id"] == "-1009000000004"
    assert call["source_kind"] == "telegram_reaction"
    assert "❤" in call["visible_text"]
    assert "今天这个方案我觉得可行" in call["visible_text"]

    # 关键：绝不触发回复链路
    assert gateway.calls == []
    assert proactive_cap.calls == []


@pytest.mark.asyncio
async def test_reaction_on_other_peoples_message_is_ignored() -> None:
    """别人之间互相点表情与我无关，不应写入上下文。"""

    plugin, context_cap, _, _ = _build_plugin()
    # 没有记录过这条消息 —— 说明不是我发的
    update = _make_reaction_update(
        types.PeerChannel(channel_id=9000000004), 777, ["👍"], [12345]
    )
    await plugin._on_reaction_update(update)

    assert context_cap.calls == []


@pytest.mark.asyncio
async def test_self_reaction_is_ignored() -> None:
    """自己给自己点表情不算别人的反馈。"""

    plugin, context_cap, _, _ = _build_plugin()
    plugin._sent_messages[(-1009000000004, 999)] = ("-1009000000004", "随便说点什么")

    update = _make_reaction_update(
        types.PeerChannel(channel_id=9000000004), 999, ["❤"], [1000000001]
    )
    await plugin._on_reaction_update(update)

    assert context_cap.calls == []


@pytest.mark.asyncio
async def test_reaction_disabled_by_config() -> None:
    """开关关闭时完全不处理表情回应。"""

    plugin, context_cap, _, _ = _build_plugin(receive_reactions=False)
    plugin._sent_messages[(-1009000000004, 999)] = ("-1009000000004", "内容")

    update = _make_reaction_update(
        types.PeerChannel(channel_id=9000000004), 999, ["❤"], [12345]
    )
    await plugin._on_reaction_update(update)

    assert context_cap.calls == []


@pytest.mark.asyncio
async def test_reaction_in_topic_group_maps_back_to_topic_session() -> None:
    """话题群里表情要写回带 topic 的会话键，否则会串到 General。"""

    plugin, context_cap, _, _ = _build_plugin()
    topic_session = "-1009000000004::tg-topic::mt=5"
    plugin._sent_messages[(-1009000000004, 321)] = (topic_session, "话题里的发言")

    update = _make_reaction_update(
        types.PeerChannel(channel_id=9000000004), 321, ["🔥"], [999]
    )
    await plugin._on_reaction_update(update)

    assert len(context_cap.calls) == 1
    assert context_cap.calls[0]["stream_id"] == topic_session


def test_remember_sent_message_is_bounded() -> None:
    """自发消息表必须有界，否则长期运行会持续泄漏内存。"""

    plugin, _, _, _ = _build_plugin()
    for i in range(600):
        plugin._remember_sent_message("-1009000000004", i, f"消息{i}")

    assert len(plugin._sent_messages) == 500
    # 最早的被淘汰，最新的保留
    assert (-1009000000004, 0) not in plugin._sent_messages
    assert (-1009000000004, 599) in plugin._sent_messages


def test_remember_sent_message_strips_topic_suffix() -> None:
    """话题群会话键要还原成原始 chat_id 才能与表情更新对上。"""

    plugin, _, _, _ = _build_plugin()
    plugin._remember_sent_message("-1009000000004::tg-topic::mt=5", 42, "话题发言")

    assert (-1009000000004, 42) in plugin._sent_messages
    session_key, text = plugin._sent_messages[(-1009000000004, 42)]
    assert session_key == "-1009000000004::tg-topic::mt=5"
    assert text == "话题发言"
