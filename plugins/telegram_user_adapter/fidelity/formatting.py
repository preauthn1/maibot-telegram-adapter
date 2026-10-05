# SPDX-License-Identifier: GPL-3.0-only
# Modified 2026-10-06; see PORT_NOTICES.md.
"""实体桥接与 UTF-16 安全分段；普通聊天默认保持字面文本。"""
from typing import Any, List, Tuple
import copy
import unicodedata

from .entities import Entity, utf16_len
from .md_in import to_markdown

KINDS = {
    "Bold": "bold", "Italic": "italic", "Underline": "underline",
    "Strike": "strike", "Spoiler": "spoiler", "Code": "code", "Pre": "pre",
    "TextUrl": "text_url", "MentionName": "mention_name", "Blockquote": "blockquote",
    "CustomEmoji": "custom_emoji",
}


def valid_entities(text: str, entities: Any) -> List[Entity]:
    """拒绝越界、跨半个代理对、交叉嵌套及过量实体。"""
    bounds = {0}
    pos = 0
    for ch in text:
        pos += utf16_len(ch)
        bounds.add(pos)
    accepted = []
    ends = []
    for e in sorted(list(entities)[:100], key=lambda e: (e.offset, -e.length)):
        if e.offset not in bounds or e.end not in bounds or e.length <= 0:
            continue
        while ends and e.offset >= ends[-1]:
            ends.pop()
        if ends and e.end > ends[-1]:
            continue
        accepted.append(e)
        ends.append(e.end)
    return accepted


def inbound_entities(text: str, entities: Any) -> List[Entity]:
    result = []
    for e in list(entities or [])[:100]:
        kind = KINDS.get(type(e).__name__.removeprefix("MessageEntity"))
        if kind is None:
            continue
        result.append(Entity(kind, e.offset, e.length, url=getattr(e, "url", None),
                             user_id=getattr(e, "user_id", None), language=getattr(e, "language", None),
                             custom_emoji_id=getattr(e, "document_id", None),
                             collapsed=bool(getattr(e, "collapsed", False))))
    return valid_entities(text, result)


def inbound_markdown(text: str, entities: Any) -> str:
    return to_markdown(text, inbound_entities(text, entities))


def telegram_entities(entities: Any) -> List[Any]:
    from telethon.tl import types
    result = []
    reverse = {v: k for k, v in KINDS.items()}
    for e in entities:
        name = reverse.get(e.type)
        if name is None:
            continue
        kwargs = {"offset": e.offset, "length": e.length}
        if e.type == "text_url":
            kwargs["url"] = e.url
        elif e.type == "mention_name":
            kwargs["user_id"] = e.user_id
        elif e.type == "pre":
            kwargs["language"] = e.language or ""
        elif e.type == "custom_emoji":
            kwargs["document_id"] = e.custom_emoji_id
        elif e.type == "blockquote":
            kwargs["collapsed"] = e.collapsed
        result.append(getattr(types, "MessageEntity" + name)(**kwargs))
    return result


def prepare_outbound(text: str, parse_mode: Any, *, markdown: bool = False) -> Tuple[str, List[Any]]:
    # Existing command formatting keeps Telethon's exact parser semantics.
    if parse_mode is not None:
        from telethon.utils import sanitize_parse_mode
        body, entities = sanitize_parse_mode(parse_mode).parse(text)
        return body, list(entities or [])
    if markdown:
        from .md_out import render
        result = render(text)
        return result.text, telegram_entities(valid_entities(result.text, result.entities))
    return text, []


def split_text(text: str, entities: Any = (), limit: int = 4096) -> List[Tuple[str, List[Any]]]:
    """保留全部字符，实体跨段裁剪；不切开 Unicode 标量。

    尽量避开组合字符、ZWJ、变体与旗帜对；超长单一字素按标量切分。
    最多 16 段，防止单次响应产生无界工作。
    """
    if not 2 <= limit <= 4096 or utf16_len(text) > limit * 16:
        raise ValueError("文本超过有界分段范围")
    offsets = [0]
    for ch in text:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise ValueError("文本含孤立代理字符")
        offsets.append(offsets[-1] + utf16_len(ch))
    bounds = set(offsets)
    entities = list(entities or [])
    if len(entities) > 100:
        raise ValueError("实体过多")
    for e in entities:
        if e.offset not in bounds or e.offset + e.length not in bounds or e.length <= 0:
            raise ValueError("实体不是有效 UTF-16 范围")
    chunks = []
    start = 0
    while start < len(text):
        end = start
        while end < len(text) and offsets[end + 1] - offsets[start] <= limit:
            end += 1
        hard_end = end
        if end < len(text):
            while end > start and (unicodedata.combining(text[end]) or text[end] in "\u200d\ufe0e\ufe0f"
                                  or text[end - 1] == "\u200d" or 0x1F3FB <= ord(text[end]) <= 0x1F3FF
                                  or (0x1F1E6 <= ord(text[end]) <= 0x1F1FF and 0x1F1E6 <= ord(text[end-1]) <= 0x1F1FF)):
                end -= 1
            if end == start:
                end = hard_end
        lo, hi = offsets[start], offsets[end]
        adjusted = []
        for e in entities:
            left, right = max(e.offset, lo), min(e.offset + e.length, hi)
            if right <= left:
                continue
            if isinstance(e, Entity):
                item = e.moved(left - lo, right - left)
            else:
                item = copy.copy(e)
                item.offset, item.length = left - lo, right - left
            adjusted.append(item)
        chunks.append((text[start:end], adjusted))
        start = end
    return chunks
