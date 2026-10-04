"""合法显式对象替换仍生效，混合输入不复活旧ID。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector
from src.chat.replyer import maisaka_generator_base as generator_module
from src.llm_models.model_client.openai_client import _convert_messages

@pytest.mark.parametrize('include_invalid', [False, True, 'duplicate'])
def test_valid_override_survives_normalization_and_request(monkeypatch, include_invalid):
    selector = MaisakaExpressionSelector()
    rows = [{'id':i,'situation':'倾诉','style':f'旧表达{i}'} for i in range(1,11)]
    monkeypatch.setattr(selector,'_can_use_expressions',lambda _:True)
    monkeypatch.setattr(selector,'_load_all_expression_candidates',lambda _:rows)
    monkeypatch.setattr(selector,'_build_expression_candidate_pool',AsyncMock(return_value=rows))
    monkeypatch.setattr(selector,'_serialize_reply_message',lambda _: {})
    usage=Mock()
    monkeypatch.setattr(selector,'_update_last_active_time',usage)
    replacement=[{'id':3,'situation':'倾诉','style':'确认对方感受，不添加建议'}]
    if include_invalid:
        replacement.insert(0, {})
        replacement.append({'id':2,'situation':'倾诉','style':''})
    if include_invalid == 'duplicate':
        replacement.extend([
            {'id':2,'situation':'倾诉','style':'冲突表达甲'},
            {'id':2,'situation':'倾诉','style':'冲突表达乙'},
        ])
    async def hook(name, **kwargs):
        if name.endswith('after_selection'):
            kwargs['selected_expressions']=replacement
        return SimpleNamespace(aborted=False,kwargs=kwargs)
    monkeypatch.setattr(selector,'_get_runtime_manager',lambda:SimpleNamespace(invoke_hook=hook))
    result=asyncio.run(selector.select_for_reply(session_id='synthetic',chat_history=[],
        reply_message=SimpleNamespace(processed_plain_text='只想吐槽'),reply_reason='倾诉',
        sub_agent_runner=AsyncMock(return_value='{"selected_ids":[2]}')))
    assert result.selected_expression_ids == [3]
    assert len(result.selected_expressions) == 1
    assert '确认对方感受' in result.expression_habits
    assert '旧表达' not in result.expression_habits
    assert '冲突表达' not in result.expression_habits
    usage.assert_called_once_with([3])
    generator=object.__new__(generator_module.BaseMaisakaReplyGenerator)
    monkeypatch.setattr(generator,'_build_keyword_reaction_prompt',lambda **kw:'')
    monkeypatch.setattr(generator,'_build_system_prompt',lambda **kw:'合成系统提示')
    monkeypatch.setattr(generator,'_build_final_user_message',lambda **kw:'只想吐槽，不要建议')
    monkeypatch.setattr(generator,'_select_temporary_reply_style',lambda:'')
    wire=_convert_messages(generator._build_request_messages([],None,'',expression_habits=result.expression_habits))
    assert len(wire)==3
    assert wire[1]['content']==result.expression_habits
    assert wire[-1]['content']=='只想吐槽，不要建议'
