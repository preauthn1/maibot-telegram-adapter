"""使用真实历史转换，确认已发送回复与未发送模型输出不混同。"""
from datetime import datetime, timezone
from src.common.data_models.message_component_data_model import MessageSequence
from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
from src.maisaka.context.messages import SessionBackedMessage, ModelOutputContextMessage
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType


def test_real_history_preserves_correction_and_sent_reply(monkeypatch):
    generator = object.__new__(BaseMaisakaReplyGenerator)
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_build_system_prompt', lambda **kw: '合成系统提示')
    monkeypatch.setattr(generator, '_build_target_message_block', lambda _: '')
    monkeypatch.setattr(generator, '_build_reply_attachment_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_select_temporary_reply_style', lambda: '')
    now = datetime.now(timezone.utc)
    sent_text = '这是之前的详细答复。' * 70 + '\n```python\nif ready:\n    run()\n```\n但尚未执行，不能当作已完成。'
    history = [
        SessionBackedMessage(raw_message=MessageSequence(components=[]), visible_text='旧系统是 Ubuntu', timestamp=now),
        SessionBackedMessage(raw_message=MessageSequence(components=[]), visible_text=sent_text, timestamp=now, source_kind='guided_reply'),
        SessionBackedMessage(raw_message=MessageSequence(components=[]), visible_text='纠正：当前是 Alpine，不是 Ubuntu', timestamp=now),
        ModelOutputContextMessage(output_item=ContextItemBuilder().set_role(RoleType.Assistant).add_text_content('UNSENT_DRAFT').build()),
    ]
    items = generator._build_request_messages(history, None, '', reply_requirements='只回复当前系统名称')
    texts = [''.join(getattr(p, 'text', '') for p in getattr(i, 'parts', ())) for i in items]
    assert texts[1:4] == ['旧系统是 Ubuntu', sent_text, '纠正：当前是 Alpine，不是 Ubuntu']
    assert getattr(items[2], 'role', None) == RoleType.Assistant
    assert '只回复当前系统名称' in texts[-1]
    assert 'UNSENT_DRAFT' not in '\n'.join(texts)
