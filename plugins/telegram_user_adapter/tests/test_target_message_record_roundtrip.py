"""消息记录编解码后，当前目标仍保留分片、媒体边界与引用归属。"""
from datetime import datetime, timezone
import pytest
from src.chat.message_receive.message import SessionMessage
from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
from src.common.data_models.message_component_data_model import (
    MessageSequence, TextComponent, ReplyComponent, ImageComponent, StandardMessageComponents,
)
from src.chat.replyer import maisaka_generator_base as module


@pytest.mark.parametrize('with_media', [False, True])
@pytest.mark.parametrize('persist', [False, True])
def test_target_record_roundtrip_preserves_content(monkeypatch, tmp_path, with_media, persist):
    message = SessionMessage('synthetic-target', datetime(2026, 1, 1, tzinfo=timezone.utc), 'synthetic')
    message.session_id = 'synthetic-session'
    message.message_info = MessageInfo(user_info=UserInfo('synthetic-user', '合成用户'))
    message.processed_plain_text = 'STALE_PROCESSED_TEXT'
    text = '背景说明。' * 80 + '\n```python\nif ready:\n    run()\n```\n不要执行，只保留原文。'
    components: list[StandardMessageComponents] = [TextComponent(text=char) for char in text]
    components.insert(12, ReplyComponent(target_message_id='synthetic-quote',
                                        target_message_content='STALE_QUOTE_TEXT'))
    expected = text
    if with_media:
        components.extend([ImageComponent(binary_hash='synthetic-image', content='[合成图片]'),
                           TextComponent(text='\n\n    图片后不要追加建议。')])
        expected += ' [合成图片]\n\n    图片后不要追加建议。'
    message.raw_message = MessageSequence(components=components)
    # 真实数据库记录对象和编解码，不连接或写入生产数据库。
    record = message.to_db_instance()
    original_raw_content = record.raw_content
    if persist:
        from sqlmodel import Session, create_engine, select
        from src.common.database.database_model import Messages
        database_url = f'sqlite:///{tmp_path / "target-roundtrip.db"}'
        engine = create_engine(database_url)
        Messages.__table__.create(engine)
        try:
            with Session(engine) as session:
                session.add(record)
                session.commit()
        finally:
            engine.dispose()
        # 关闭写入连接后重新建引擎，确保检查的是磁盘回读而非 ORM 身份缓存。
        reader = create_engine(database_url)
        try:
            with Session(reader) as session:
                loaded = session.exec(select(Messages)).one()
                assert loaded.raw_content == original_raw_content
                assert loaded.message_id == message.message_id
                assert loaded.processed_plain_text == 'STALE_PROCESSED_TEXT'
                restored = SessionMessage.from_db_instance(loaded)
        finally:
            reader.dispose()
    else:
        restored = SessionMessage.from_db_instance(record)
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    monkeypatch.setattr(module, 'is_bot_self', lambda *args: False)
    assert generator._build_target_message_content(restored) == expected
    block = generator._build_target_message_block(restored)
    assert expected in block
    assert 'synthetic-quote' in block
    assert 'STALE_QUOTE_TEXT' not in block
    assert 'STALE_PROCESSED_TEXT' not in block
    assert restored.session_id == message.session_id
    assert restored.message_info.user_info == message.message_info.user_info
