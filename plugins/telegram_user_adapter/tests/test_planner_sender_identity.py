"""账号身份来自元数据，不依赖可能重复或变化的昵称。"""
from datetime import datetime
from types import SimpleNamespace
from src.maisaka.context.planner_messages import build_planner_user_prefix_from_session_message
from src.common.data_models.message_component_data_model import MessageSequence


def message(uid):
    return SimpleNamespace(timestamp=datetime(2026,1,1), message_id='m', session_id='s',
        platform='telegram', is_notify=False, raw_message=MessageSequence([]),
        message_info=SimpleNamespace(user_info=SimpleNamespace(user_id=uid,user_nickname='同名',user_cardname='同名')))


def test_same_name_accounts_remain_distinguishable():
    a=build_planner_user_prefix_from_session_message(message('17'))
    b=build_planner_user_prefix_from_session_message(message('29'))
    assert a != b
    assert 'sender_id="17"' in a and 'sender_id="29"' in b
    assert 'sender_platform="telegram"' in a


def test_sender_identity_survives_real_history_and_replyer_conversion():
    import asyncio
    from src.maisaka.reasoning_engine import MaisakaReasoningEngine
    from src.chat.replyer.maisaka_generator_base import BaseMaisakaReplyGenerator
    from src.llm_models.model_client.openai_client import _convert_messages

    async def run():
        engine = object.__new__(MaisakaReasoningEngine)
        engine._runtime = SimpleNamespace(_is_focus_mode_active_for_current_chat=lambda: False)
        originals = [message('17'), message('29')]
        bodies = ['我在衡阳当护士。', '我在潍坊教数学。']
        history = []
        for original, body in zip(originals, bodies):
            original.raw_message.text(body)
            history.append(await engine._build_history_message(original, source_kind='user'))
        # 已构造的历史应保留接收时身份，不随可变原消息对象变化。
        originals[0].message_info.user_info.user_id = 'changed'
        originals[0].message_info.user_info.user_nickname = '改名'
        generator = object.__new__(BaseMaisakaReplyGenerator)
        wire = _convert_messages(generator._build_history_messages(history, enable_visual_message=False))
        assert len(wire) == 2
        for entry, uid, body in zip(wire, ['17', '29'], bodies):
            assert entry['role'] == 'user'
            content = entry['content']
            text = content if isinstance(content, str) else ''.join(p.get('text', '') for p in content)
            assert f'sender_id="{uid}"' in text
            assert 'sender_platform="telegram"' in text
            assert body in text
            assert 'changed' not in text and '改名' not in text
    asyncio.run(run())


def test_sender_metadata_is_attribute_escaped():
    result=build_planner_user_prefix_from_session_message(message('17"<>&'))
    assert 'sender_id="17&quot;&lt;&gt;&amp;"' in result
