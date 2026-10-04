"""会话类型不是隐私或访问权限证明。"""
from src.chat.message_receive.chat_manager import BotChatSession
from src.chat.utils import scene_context as module


def test_private_scene_does_not_guarantee_exclusive_access(monkeypatch):
    monkeypatch.setattr(module, '_load_account_profile', lambda: {})
    session = BotChatSession(session_id='synthetic-private', platform='telegram',
                             user_id='7', user_nickname='合成用户')
    text = module.build_scene_context_block(session)
    assert '**一对一私聊**' in text
    assert '合成用户' in text
    assert '没有其他人在看' not in text
    assert '只有你和' not in text
    assert '不能据此保证' in text
