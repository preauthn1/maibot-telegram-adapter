"""显式对象替换无效时，不通过遗留ID复活旧表达。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector

@pytest.mark.parametrize('replacement', [[{}], [{'id':2,'situation':'倾诉','style':''}]])
def test_invalid_explicit_override_does_not_restore_old_selection(monkeypatch, replacement):
    selector = MaisakaExpressionSelector()
    rows = [{'id':i,'situation':'倾诉','style':f'合成表达{i}'} for i in range(1,11)]
    monkeypatch.setattr(selector,'_can_use_expressions',lambda _:True)
    monkeypatch.setattr(selector,'_load_all_expression_candidates',lambda _:rows)
    monkeypatch.setattr(selector,'_build_expression_candidate_pool',AsyncMock(return_value=rows))
    monkeypatch.setattr(selector,'_serialize_reply_message',lambda _: {})
    usage=Mock()
    monkeypatch.setattr(selector,'_update_last_active_time',usage)
    async def hook(name, **kwargs):
        if name.endswith('after_selection'):
            kwargs['selected_expressions']=replacement
        return SimpleNamespace(aborted=False,kwargs=kwargs)
    monkeypatch.setattr(selector,'_get_runtime_manager',lambda:SimpleNamespace(invoke_hook=hook))
    result=asyncio.run(selector.select_for_reply(session_id='synthetic',chat_history=[],
        reply_message=SimpleNamespace(processed_plain_text='只想吐槽'),reply_reason='倾诉',
        sub_agent_runner=AsyncMock(return_value='{"selected_ids":[2]}')))
    assert result.selected_expression_ids == []
    assert result.expression_habits == ''
    usage.assert_not_called()
