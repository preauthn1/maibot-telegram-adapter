"""Actual planner assembly and OpenAI conversion preserve reference roles/order."""
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.llm_models.model_client.openai_client import _convert_messages

@pytest.mark.parametrize('profile', [
    '【人物画像-内部参考】\n合成人物喜欢茶。',
    '【人物画像-内部参考】\n合成人工覆盖：喜欢咖啡。',
])
def test_planner_profile_openai_message_wire(monkeypatch, profile):
    loop = object.__new__(MaisakaChatLoopService)
    monkeypatch.setattr(loop, '_build_current_chat_attention_tail_message', lambda: '合成注意事项')
    monkeypatch.setattr(loop, '_build_current_time_user_message', lambda: '合成时间')
    history = []
    injected = ['合成工具提醒', profile]
    tails = ['合成当前任务']
    items = loop._build_request_messages(history, enable_visual_message=False,
        injected_user_messages=injected, tail_user_messages=tails,
        final_user_message='合成最终约束', system_prompt='合成系统人设')
    assert _convert_messages(items) == [
        {'role': 'system', 'content': '合成系统人设'},
        {'role': 'user', 'content': '合成工具提醒'},
        {'role': 'user', 'content': profile},
        {'role': 'user', 'content': '合成时间'},
        {'role': 'user', 'content': '合成当前任务'},
        {'role': 'user', 'content': '合成注意事项'},
        {'role': 'user', 'content': '合成最终约束'},
    ]
    assert history == []
    assert injected == ['合成工具提醒', profile]
    assert tails == ['合成当前任务']
