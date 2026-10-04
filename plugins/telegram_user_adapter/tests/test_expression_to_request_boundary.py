"""公开表达选择入口到请求装配；撤回不得残留，外部依赖隔离。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector
from src.chat.replyer import maisaka_generator_base as module
from src.llm_models.model_client.openai_client import _convert_messages


@pytest.mark.parametrize('withdraw', [False, True])
def test_expression_selection_reaches_request_without_withdrawn_residue(monkeypatch, withdraw):
    selector = object.__new__(MaisakaExpressionSelector)
    candidates = [{'id': i, 'situation': '倾诉', 'style': f'合成表达标记{i}'} for i in range(1, 11)]
    monkeypatch.setattr(selector, '_can_use_expressions', lambda _: True)
    monkeypatch.setattr(selector, '_load_all_expression_candidates', lambda _: candidates)
    monkeypatch.setattr(selector, '_build_expression_candidate_pool', AsyncMock(return_value=candidates))
    monkeypatch.setattr(selector, '_build_chat_info', lambda _: '')
    monkeypatch.setattr(selector, '_serialize_reply_message', lambda _: {})
    usage = Mock()
    monkeypatch.setattr(selector, '_update_last_active_time', usage)
    async def hook(name, **kwargs):
        if name.endswith('after_selection') and withdraw:
            kwargs['selected_expressions'] = []
        return SimpleNamespace(aborted=False, kwargs=kwargs)
    monkeypatch.setattr(selector, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
    runner = AsyncMock(return_value='{"selected_ids":[2]}')
    result = asyncio.run(selector.select_for_reply(session_id='synthetic', chat_history=[],
        reply_message=SimpleNamespace(processed_plain_text='只听我吐槽，不要建议'),
        reply_reason='倾诉', sub_agent_runner=runner))
    runner.assert_awaited_once()
    generator = object.__new__(module.BaseMaisakaReplyGenerator)
    monkeypatch.setattr(generator, '_build_keyword_reaction_prompt', lambda **kw: '')
    monkeypatch.setattr(generator, '_build_system_prompt', lambda **kw: '合成系统提示')
    monkeypatch.setattr(generator, '_build_final_user_message', lambda **kw: kw['reply_requirements'])
    monkeypatch.setattr(generator, '_select_temporary_reply_style', lambda: '')
    wire = _convert_messages(generator._build_request_messages([], None, '',
        expression_habits=result.expression_habits, reply_requirements='只听我吐槽，不要建议'))
    assert wire[-1] == {'role':'user', 'content':'只听我吐槽，不要建议'}
    if withdraw:
        assert result.selected_expression_ids == [] and result.expression_habits == ''
        assert len(wire) == 2
        usage.assert_not_called()
    else:
        assert result.selected_expression_ids == [2]
        assert len(wire) == 3 and '合成表达标记2' in wire[1]['content']
        assert '合成表达标记3' not in wire[1]['content']
        usage.assert_called_once_with([2])
