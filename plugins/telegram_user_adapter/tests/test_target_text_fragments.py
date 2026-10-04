"""连续文本组件分片不应改变代码、单词或空白。"""
from types import SimpleNamespace
import pytest
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator, TextComponent


@pytest.mark.parametrize('fragments', [
    ['不要', '执行'],
    ['```python\nif ready:\n', '    run()\n```'],
    ['保留', '\n\n', '分段'],
    ['https://example.', 'invalid/path'],
])
def test_adjacent_text_fragments_preserve_content(fragments):
    generator = object.__new__(BaseMaisakaReplyGenerator)
    message = SimpleNamespace(raw_message=SimpleNamespace(components=[
        TextComponent(text=text) for text in fragments]), processed_plain_text='STALE')
    assert generator._build_target_message_content(message) == ''.join(fragments).strip()


@pytest.mark.parametrize('left,right', [
    ('说明\n', '\n    保留缩进'),
    ('说明\n\n', '\n\n后续'),
    ('说明', '后续'),
])
def test_media_boundary_preserves_text_whitespace(left, right):
    from src.common.data_models.message_component_data_model import ImageComponent
    generator = object.__new__(BaseMaisakaReplyGenerator)
    message = SimpleNamespace(raw_message=SimpleNamespace(components=[
        TextComponent(text=left),
        ImageComponent(binary_hash='synthetic', content='[合成图片]'),
        TextComponent(text=right),
    ]), processed_plain_text='STALE')
    separator_before = '' if left[-1].isspace() else ' '
    separator_after = '' if right[0].isspace() else ' '
    expected = left + separator_before + '[合成图片]' + separator_after + right
    assert generator._build_target_message_content(message) == expected


def test_reply_metadata_does_not_split_text():
    from src.common.data_models.message_component_data_model import ReplyComponent
    generator = object.__new__(BaseMaisakaReplyGenerator)
    message = SimpleNamespace(raw_message=SimpleNamespace(components=[
        TextComponent(text='```python\nif ready:\n'),
        ReplyComponent(target_message_id='synthetic-quote', target_message_content='STALE_QUOTE'),
        TextComponent(text='    run()\n```'),
    ]), processed_plain_text='STALE')
    assert generator._build_target_message_content(message) == '```python\nif ready:\n    run()\n```'
