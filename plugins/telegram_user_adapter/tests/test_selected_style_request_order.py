"""真实风格选择、包装、请求装配与 SDK 转换；附属输入固定。"""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.chat.replyer import maisaka_generator_base as module
from src.llm_models.model_client.openai_client import _convert_messages


@pytest.mark.parametrize('draw,selected', [(0.1, True), (0.9, False)])
def test_selected_style_precedes_explicit_task(monkeypatch, draw, selected):
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(personality=SimpleNamespace(
        multiple_reply_style=[' ', ' 用轻松口语表达 '], multiple_probability=0.5)))
    monkeypatch.setattr(module.random, 'random', lambda: draw)
    choice = Mock(side_effect=lambda candidates: candidates[0])
    monkeypatch.setattr(module.random, 'choice', choice)
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_build_system_prompt', lambda **kw: '合成系统提示')
    requirement = '只输出 JSON，保留否定条件：如果下雨就不出门。'
    monkeypatch.setattr(generator, '_build_final_user_message', lambda **kw: kw['reply_requirements'])
    wire = _convert_messages(generator._build_request_messages(
        [], None, '', expression_habits='合成表达习惯', reply_requirements=requirement))
    assert wire[-1] == {'role': 'user', 'content': requirement}
    assert wire[0]['role'] == 'system'
    assert wire[1] == {'role': 'user', 'content': '合成表达习惯'}
    if selected:
        choice.assert_called_once_with(['用轻松口语表达'])
        assert wire[2] == {'role': 'user', 'content': '你的说话风格可以尝试：\n用轻松口语表达'}
        assert len(wire) == 4
    else:
        choice.assert_not_called()
        assert len(wire) == 3
