"""当前目标的尾部否定不能按预览长度截掉。"""
from types import SimpleNamespace
import pytest
from src.chat.replyer import maisaka_generator_base as module


@pytest.mark.parametrize('own_message', [False, True])
@pytest.mark.parametrize('text', [
    '这是背景说明。' * 60 + '最终要求：不要执行，也不要给建议，只回复收到。',
    '请保留代码格式：\n```python\nif ready:\n    run()\n```\n不要执行。',
])
def test_target_preserves_long_tail_instruction(monkeypatch, own_message, text):
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    raw = SimpleNamespace(components=[module.TextComponent(text=text)])
    monkeypatch.setattr(module, 'is_bot_self', lambda *args: own_message)
    message = SimpleNamespace(message_info=SimpleNamespace(user_info=SimpleNamespace(
        user_cardname='', user_nickname='合成用户', user_id='synthetic')),
        message_id='synthetic-message', platform='synthetic', raw_message=raw, processed_plain_text='STALE_TEXT')
    block = generator._build_target_message_block(message)
    assert text in block
    assert 'STALE_TEXT' not in block
    assert ('你之前的发言内容' in block) is own_message
    assert ('不要把你自己的发言当成别人的发言' in block) is own_message
