"""离线断言：真实模块 + Telethon Document + 假传输，无网络/pytest。"""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import asyncio
import logging
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from telethon.tl.types import Document, DocumentAttributeSticker, InputStickerSetID, StickerPack

pkg = "plugins.telegram_user_adapter"
from plugins.telegram_user_adapter.official_stickers import OfficialDuckStickers, PACK_SET_ID
from plugins.telegram_user_adapter.codecs.outbound import TelegramUserOutboundCodec
from plugins.telegram_user_adapter.telegram_user_client import TelegramUserClient
from plugins.telegram_user_adapter.plugin import TelegramUserAdapterPlugin


def fixture():
    doc = Document(id=101, access_hash=2, file_reference=b"fresh", date=datetime.now(timezone.utc),
                   mime_type="application/x-tgsticker", size=1, dc_id=2,
                   attributes=[DocumentAttributeSticker(alt="😂", stickerset=InputStickerSetID(PACK_SET_ID, 3))])
    return SimpleNamespace(set=SimpleNamespace(short_name="UtyaDuck", id=PACK_SET_ID, access_hash=3,
                                               official=False, masks=False, emojis=False),
                           documents=[doc], packs=[StickerPack(emoticon="😂", documents=[101]),
                                                  StickerPack(emoticon="🦆", documents=[101])])


class Transport:
    def __init__(self):
        self.sent = []
        self.result = fixture()

    async def __call__(self, request):
        assert type(request).__name__ == "GetStickerSetRequest"
        assert request.stickerset.short_name == "UtyaDuck" and request.hash == 0
        return self.result

    async def send_file(self, entity, document, **kwargs):
        assert isinstance(document, Document)
        self.sent.append((entity, document, kwargs))
        return SimpleNamespace(id=7, sticker=document)

    async def get_entity(self, value):
        return value


async def main():
    c = OfficialDuckStickers()
    c.install(fixture())
    assert c.select("😂")[1].id == 101
    assert c.select("🦆") is None
    assert c.select("https://example.invalid/x.png") is None
    assert c.select({"pack": "Other", "emoji": "😂"}) is None
    assert c.select({"pack": "UtyaDuck", "emoji": "😂", "document_id": 999}) is None
    assert c.reserve("synthetic", now=1)
    assert not c.reserve("other", now=1)
    c.finish("synthetic", success=False)
    assert c.reserve("synthetic", now=2)
    c.finish("synthetic", success=True, now=2)
    assert not c.reserve("synthetic", now=500)
    transport = Transport()
    wrapper = object.__new__(TelegramUserClient)
    wrapper._client = transport
    codec = TelegramUserOutboundCodec(wrapper, logging.getLogger("offline"))
    codec.stickers.install(fixture())
    # 走真正出站 codec，话题根路由、原生 Document 与预算计数均在原路径。
    payload = {"message_info": {"group_info": {"group_id": "-1009000000001::tg-topic::mt=42"}},
               "raw_message": [{"type": "text", "data": "😂"}]}
    result = await codec.send_outbound_message(payload, {})
    assert result["success"], result
    assert transport.sent[-1][2]["reply_to"] == 42
    assert result["text_observations"][0]["native_sticker"]["document_id"] == 101
    assert not result["metadata"]["delivery_content"]["complete"]
    count = len(transport.sent)
    assert not (await codec.send_outbound_message(payload, {}))["success"]
    assert len(transport.sent) == count
    # 实际 SDK Tool 方法 -> 捕获的 gateway 边界 -> 实际 codec；不声明队列闸门实测。
    plugin = TelegramUserAdapterPlugin()
    plugin._outbound_codec = TelegramUserOutboundCodec(wrapper, logging.getLogger("offline"))
    plugin._outbound_codec.stickers.install(fixture())
    target = "-1009000000001::tg-topic::mt=42"
    plugin._sticker_contexts.add(target)
    plugin._sticker_routes["synthetic-stream"] = (target, True)
    captured = []
    async def gateway(message, *args, **kwargs):
        captured.append(message)
        return await plugin._outbound_codec.send_outbound_message(message, {})
    plugin.handle_telegram_user_gateway = gateway
    result = await plugin.official_duck_sticker(action="send", emoji="😂", platform="telegram", stream_id="synthetic-stream", group_id="ignored-model-destination")
    assert result["success"] and captured[0]["raw_message"][0]["type"] == "sticker"
    assert transport.sent[-1][2]["reply_to"] == 42
    assert not (await plugin.official_duck_sticker(action="send", emoji="😂", platform="other", group_id=target))["success"]
    bad = fixture()
    bad.set.id += 1
    try:
        c.install(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("unapproved set accepted")
    assert c.select("😂") is None
    print("PASS: pinned identity, exact emoji, foreign/file/stale rejection, reserve rollback/cooldown, native wrapper, text replacement, topic routing, observations, SDK tool boundary")


if __name__ == "__main__":
    asyncio.run(main())
