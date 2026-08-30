"""Telegram 真人账号表情回应（reaction）解析。

NewMessage 事件不包含「有人给某条消息点了表情」这类更新，只能通过
``events.Raw`` 监听底层 MTProto ``UpdateMessageReactions``。本模块把该
更新对象解析成插件可消费的结构化信息，用于「谁给我发的哪条消息点了什么表情」。
"""

from __future__ import annotations

from typing import Any, List, Optional

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReactionInfo:
    """一次表情回应更新的解析结果。

    Attributes:
        chat_id: 归一化后的会话 ID（群/频道为 ``-100`` 前缀，私聊为对方用户 ID）。
        message_id: 被点表情的消息 ID。
        emojis: 本次更新里出现的表情列表（emoji 字符或自定义表情占位）。
        reactor_ids: 最近点表情的用户 ID 列表（Telegram 仅在部分场景下提供）。
    """

    chat_id: int
    message_id: int
    emojis: List[str] = field(default_factory=list)
    reactor_ids: List[str] = field(default_factory=list)


def _normalize_peer_to_chat_id(peer: Any) -> Optional[int]:
    """把 MTProto Peer 归一化为与 event.chat_id 一致的会话 ID。

    Telethon 对超级群/频道统一使用 ``-100`` 前缀的负数 ID，私聊使用正数用户 ID，
    这里与之对齐，保证 reaction 的 chat_id 能和入站消息的 chat_id 匹配。

    Args:
        peer: MTProto ``PeerUser`` / ``PeerChat`` / ``PeerChannel``。

    Returns:
        Optional[int]: 归一化会话 ID；无法识别时返回 ``None``。
    """

    from telethon.tl import types

    if isinstance(peer, types.PeerUser):
        return int(peer.user_id)
    if isinstance(peer, types.PeerChat):
        # 普通群（非超级群）使用负数群 ID。
        return -int(peer.chat_id)
    if isinstance(peer, types.PeerChannel):
        # 超级群/频道使用 -100 前缀。
        return int(f"-100{peer.channel_id}")
    return None


def _extract_emoji(reaction: Any) -> Optional[str]:
    """从单个 Reaction 对象提取可读表情。

    Args:
        reaction: MTProto ``ReactionEmoji`` / ``ReactionCustomEmoji``。

    Returns:
        Optional[str]: emoji 字符或自定义表情占位；无法识别时返回 ``None``。
    """

    from telethon.tl import types

    if isinstance(reaction, types.ReactionEmoji):
        emoticon = str(reaction.emoticon or "").strip()
        return emoticon or None
    if isinstance(reaction, types.ReactionCustomEmoji):
        # 自定义表情只有 document_id，拿不到语义，用占位标注避免误读。
        return "[自定义表情]"
    return None


def parse_reaction_update(update: Any) -> Optional[ReactionInfo]:
    """把 ``UpdateMessageReactions`` 解析成结构化信息。

    Args:
        update: Telethon 原始 MTProto Update 对象。

    Returns:
        Optional[ReactionInfo]: 解析结果；不是表情更新或没有有效表情时返回 ``None``。
    """

    from telethon.tl import types

    if not isinstance(update, types.UpdateMessageReactions):
        return None

    chat_id = _normalize_peer_to_chat_id(update.peer)
    message_id = int(getattr(update, "msg_id", 0) or 0)
    if chat_id is None or message_id <= 0:
        return None

    reactions = getattr(update, "reactions", None)
    if reactions is None:
        return None

    emojis: List[str] = []
    # results 是聚合后的表情计数，取当前消息上出现过的所有表情种类。
    for result in getattr(reactions, "results", None) or []:
        emoji = _extract_emoji(getattr(result, "reaction", None))
        if emoji and emoji not in emojis:
            emojis.append(emoji)

    reactor_ids: List[str] = []
    # recent_reactions 才带具体是谁点的（Telegram 只在可见成员列表的会话提供）。
    for peer_reaction in getattr(reactions, "recent_reactions", None) or []:
        reactor_chat_id = _normalize_peer_to_chat_id(getattr(peer_reaction, "peer_id", None))
        if reactor_chat_id is not None:
            reactor_id = str(reactor_chat_id)
            if reactor_id not in reactor_ids:
                reactor_ids.append(reactor_id)

    if not emojis:
        return None

    return ReactionInfo(
        chat_id=chat_id,
        message_id=message_id,
        emojis=emojis,
        reactor_ids=reactor_ids,
    )
