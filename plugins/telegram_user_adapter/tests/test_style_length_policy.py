"""自动历史长度不得代替人工硬限制。"""
from pathlib import Path
from types import SimpleNamespace
import logging
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter.codecs import outbound


@pytest.mark.parametrize('inferred,manual,expected', [(10, 100, 100), (10, 0, 0), (100, 22, 22)])
def test_only_manual_limit_blocks_sending(monkeypatch, inferred, manual, expected):
    profile = SimpleNamespace(style_enabled=True, style_max_chars=inferred, max_chars=manual,
                              allow_emoji_only=False, max_emoji=1, preserve_trailing_period=True)
    monkeypatch.setattr(outbound, 'get_chat_profile', lambda _: profile)
    codec = outbound.TelegramUserOutboundCodec(object(), logging.getLogger(__name__))
    assert codec.resolve_style_policy('test').max_chars == expected
