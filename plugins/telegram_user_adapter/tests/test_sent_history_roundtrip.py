"""真实消息→运行时内存历史→replyer；无平台发送、数据库或后台任务。"""
from datetime import datetime, timezone
import asyncio
from unittest.mock import AsyncMock
import pytest
from src.services import send_service
from src.chat.heart_flow.heartflow_manager import heartflow_manager
from src.maisaka.context.messages import SessionBackedMessage
from src.chat.message_receive.message import SessionMessage
from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
from src.common.data_models.message_component_data_model import MessageSequence, TextComponent
from src.maisaka.runtime import MaisakaHeartFlowChatting
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
from src.llm_models.payload_content.context_item import RoleType


@pytest.mark.parametrize('success', [True, False])
@pytest.mark.parametrize('aux_failure', [None, '_schedule_sent_image_recognition', '_emit_monitor_message_sent'])
@pytest.mark.parametrize('sent_text', [
    '当前是 Alpine，不是 Ubuntu。',
    '[尚未执行]这只是方案，不代表已经完成。',
    '[说明](https://example.invalid/docs)\n请保留链接。',
    '这是详细方案。' * 90 + '\n```python\nif ready:\n    run()\n```\n只是方案，尚未执行，不代表已经完成。',
])
@pytest.mark.parametrize('nickname', ['合成助手', '合成]助手'])
def test_sent_message_roundtrip(monkeypatch, success, aux_failure, sent_text, nickname):
    runtime = object.__new__(MaisakaHeartFlowChatting)
    runtime._chat_history = []
    runtime.log_prefix = '[synthetic]'
    monkeypatch.setattr(runtime, '_is_focus_mode_active_for_current_chat', lambda: False)
    monkeypatch.setattr(runtime, '_schedule_sent_image_recognition', lambda _: None)
    monkeypatch.setattr(runtime, '_emit_monitor_message_sent', lambda **kw: None)
    if aux_failure:
        def broken(*args, **kwargs):
            raise RuntimeError('synthetic auxiliary failure')
        monkeypatch.setattr(runtime, aux_failure, broken)
    outcomes = []
    real_append = runtime.append_sent_message_to_chat_history
    def tracked_append(*args, **kwargs):
        outcome = real_append(*args, **kwargs)
        outcomes.append(outcome)
        return outcome
    monkeypatch.setattr(runtime, 'append_sent_message_to_chat_history', tracked_append)
    message = SessionMessage('synthetic-sent', datetime.now(timezone.utc), 'telegram')
    message.session_id = 'synthetic-session'
    message.message_info = MessageInfo(UserInfo('synthetic-bot', nickname))
    from src.common.data_models.message_component_data_model import ReplyComponent
    # 平台返回带引用元数据的单字符分片，验证完整历史路径不会改写正文。
    fragments = [TextComponent(text=char) for char in sent_text]
    message.raw_message = MessageSequence(components=[
        *fragments[:3],
        ReplyComponent(target_message_id='synthetic-quote', target_message_content='STALE_QUOTED_BODY'),
        *fragments[3:],
    ])
    message.processed_plain_text = sent_text
    monkeypatch.setattr(heartflow_manager, 'heartflow_chat_list', {'synthetic-session': runtime})
    original = SessionMessage('synthetic-before-send', message.timestamp, 'telegram')
    original.session_id = message.session_id
    io = AsyncMock(return_value=message if success else None)
    monkeypatch.setattr(send_service, '_send_via_platform_io', io)
    result = asyncio.run(send_service.send_session_message_with_message(
        original, sync_to_maisaka_history=True, maisaka_source_kind='guided_reply',
        storage_message=False, show_log=False))
    io.assert_awaited_once()
    if not success:
        assert result is None
        assert runtime._chat_history == []
        return
    assert result is message
    assert outcomes == [True]
    assert len(runtime._chat_history) == 1
    entry = runtime._chat_history[0]
    assert isinstance(entry, SessionBackedMessage)
    assert entry.source_kind == 'guided_reply'
    assert entry.message_id == 'synthetic-sent'
    # 原消息对象可能随后刷新昵称；历史正文不应依赖可变对象重建前缀。
    message.message_info.user_info.user_nickname = '更新后的昵称'
    generator = object.__new__(BaseMaisakaReplyGenerator)
    items = generator._build_history_messages(runtime._chat_history, False)
    assert len(items) == 1
    assert getattr(items[0], 'role', None) == RoleType.Assistant
    text = ''.join(getattr(p, 'text', '') for p in getattr(items[0], 'parts', ()))
    assert text == sent_text
