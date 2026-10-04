"""回复目标必须携带与历史相同的平台内账号身份。"""
from datetime import datetime
from types import SimpleNamespace
from src.chat.replyer import maisaka_generator_base as module
from src.common.data_models.message_component_data_model import MessageSequence


def test_target_preserves_sender_metadata(monkeypatch):
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    monkeypatch.setattr(module, 'is_bot_self', lambda *a: False)
    monkeypatch.setattr(generator, '_build_target_message_content', lambda m: '合成问题')
    def target(uid):
        return SimpleNamespace(platform='telegram', message_id='m', session_id='s',
            timestamp=datetime(2026,1,1), is_notify=False, raw_message=MessageSequence([]),
            message_info=SimpleNamespace(user_info=SimpleNamespace(user_id=uid,user_nickname='同名',user_cardname='')))
    first=generator._build_target_message_block(target('17'))
    second=generator._build_target_message_block(target('29'))
    assert first != second
    assert 'sender_id="17"' in first
    assert 'sender_platform="telegram"' in first
    assert '合成问题' in first
    escaped=generator._build_target_message_block(target('17"<>&'))
    assert 'sender_id="17&quot;&lt;&gt;&amp;"' in escaped
