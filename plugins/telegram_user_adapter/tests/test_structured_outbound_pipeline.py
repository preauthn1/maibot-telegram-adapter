"""真实文本出站处理到本地发送器；不连接 Telegram。"""
import asyncio
import pytest
from test_low_information_outbound import make_codec, send


@pytest.mark.parametrize('text', [
    '(a+b)*c',
    '```html\n<div>你好</div>\n```',
])
def test_structured_text_reaches_sender_unchanged(text):
    codec, sender = make_codec()
    codec._enable_humanize = True
    result = asyncio.run(send(codec, text))
    assert result is not None
    assert sender.sent == [text]


def test_requested_json_delivery_gap():
    codec, sender = make_codec()
    codec._enable_humanize = True
    text = '{"ok":true,"label":"v1中文"}'
    result = asyncio.run(send(codec, text))
    assert result is not None
    assert sender.sent == [text]
