"""固定 Telegram 频道推荐贴纸目录。

目录只保存来源消息 ID、emoji 与预期 document_id。发送前实时回源并重新
校验原消息仍来自固定频道、仍是可转发的原生贴纸且 document_id 未改变。
"""
from pathlib import Path
from typing import Any

import asyncio
import json
import secrets

_CATALOG = Path(__file__).resolve().parents[2] / "data" / "zhaxia_sticker_catalog.json"


class ChannelStickerCatalog:
    def __init__(self) -> None:
        self._refs: dict[str, dict[str, Any]] = {}

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(_CATALOG.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def search(self, query: str) -> list[dict[str, str]]:
        if not isinstance(query, str) or len(query) > 64:
            raise ValueError("查询过长")
        data = self._load()
        found: list[dict[str, str]] = []
        for item in data.get("items", []):
            if not isinstance(item, dict):
                continue
            emoji = str(item.get("emoji", ""))
            if query.casefold() not in emoji.casefold():
                continue
            token = secrets.token_urlsafe(24)
            self._refs[token] = dict(item)
            found.append({"sticker_ref": token, "emoji": emoji, "source": "zhaxia_cn"})
            if len(found) >= 20:
                break
        return found

    async def resolve(self, client: Any, token: str) -> tuple[str, Any, Any]:
        item = self._refs.get(token) if isinstance(token, str) else None
        if item is None:
            raise ValueError("频道贴纸引用无效")
        data = self._load()
        username = str(data.get("source_username", ""))
        channel_id = int(data.get("source_channel_id", 0))
        message_id = int(item.get("message_id", 0))
        expected_document_id = int(item.get("document_id", 0))
        entity = await asyncio.wait_for(client.get_entity(username), 15)
        if int(getattr(entity, "id", 0)) != channel_id:
            raise ValueError("贴纸来源频道不匹配")
        message = await asyncio.wait_for(client.get_messages(entity, ids=message_id), 15)
        if message is None or not getattr(message, "sticker", None) or getattr(message, "noforwards", False):
            raise ValueError("来源消息已失效或不允许复用")
        document = getattr(message, "document", None)
        if document is None or int(getattr(document, "id", 0)) != expected_document_id:
            raise ValueError("来源贴纸已改变")
        return str(item.get("emoji", "")), document, message
