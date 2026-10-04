"""历史前缀快照的通知、名片、正文边界与来源隔离。"""
from datetime import datetime, timezone
import pytest
from src.chat.message_receive.message import SessionMessage
from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
from src.common.data_models.message_component_data_model import MessageSequence, TextComponent
from src.maisaka.context.history import build_session_message_visible_text
from src.maisaka.context.messages import SessionBackedMessage
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator


@pytest.mark.parametrize('notify', [False, True])
@pytest.mark.parametrize('card', [None, '名]片\n第二行'])
@pytest.mark.parametrize('source', ['guided_reply', 'user'])
def test_prefix_snapshot_survives_metadata_changes(notify, card, source):
    body = '[尚未执行]\n```python\n    pass\n```'
    message = SessionMessage('id]with-bracket', datetime(2026, 1, 1, tzinfo=timezone.utc), 'synthetic')
    message.message_info = MessageInfo(UserInfo('synthetic', '名]字', card))
    message.is_notify = notify
    message.raw_message = MessageSequence(components=[TextComponent(text=body)])
    visible = build_session_message_visible_text(message, include_reply_components=False)
    entry = SessionBackedMessage.from_session_message(
        message, raw_message=message.raw_message, visible_text=visible, source_kind=source)
    assert entry.visible_text_prefix is not None
    assert visible == entry.visible_text_prefix + body
    message.message_info.user_info.user_cardname = '新名片'
    message.message_id = 'new-id'
    message.timestamp = datetime(2026, 2, 1, tzinfo=timezone.utc)
    message.is_notify = not notify
    generator = object.__new__(BaseMaisakaReplyGenerator)
    assert generator._extract_guided_bot_reply(entry) == (body if source == 'guided_reply' else '')


@pytest.mark.parametrize('body', ['[尚未执行]只是方案。', '[说明](https://example.invalid/docs)'])
def test_unprefixed_snapshot_survives_original_release(body):
    message = SessionMessage('synthetic', datetime(2026, 1, 1, tzinfo=timezone.utc), 'synthetic')
    message.message_info = MessageInfo(UserInfo('synthetic', '合成助手'))
    message.raw_message = MessageSequence(components=[TextComponent(text=body)])
    entry = SessionBackedMessage.from_session_message(
        message, raw_message=message.raw_message, visible_text=body, source_kind='guided_reply')
    # 已知没有前缀与旧对象未记录前缀是两种状态；释放原对象后仍须区分。
    entry.original_message = None
    generator = object.__new__(BaseMaisakaReplyGenerator)
    assert generator._extract_guided_bot_reply(entry) == body


@pytest.mark.parametrize('speaker', ['合成助手', '名]字'])
@pytest.mark.parametrize('include_message_id', [False, True])
def test_planner_text_factory_snapshots_prefix(speaker, include_message_id):
    from src.maisaka.context.planner_messages import build_session_backed_text_message
    body = '[尚未执行]\n```python\n    pass\n```'
    entry = build_session_backed_text_message(
        speaker_name=speaker, text=body, timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        source_kind='guided_reply', message_id='synthetic', is_self_message=True,
        include_message_id=include_message_id)
    generator = object.__new__(BaseMaisakaReplyGenerator)
    assert generator._extract_guided_bot_reply(entry) == body
    from dataclasses import replace
    # 历史复制必须携带快照；正文刷新后前缀不匹配时不得误删新正文。
    copied = replace(entry, original_message=None)
    assert copied.visible_text_prefix == entry.visible_text_prefix
    assert generator._extract_guided_bot_reply(copied) == body
    changed = replace(copied, visible_text='[新限定]尚未执行')
    assert generator._extract_guided_bot_reply(changed) == '[新限定]尚未执行'
