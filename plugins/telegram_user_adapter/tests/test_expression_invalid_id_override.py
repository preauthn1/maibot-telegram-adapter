"""显式ID列表无有效候选时，不恢复原选择。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector

@pytest.mark.parametrize('replacement,expected', [
    ([999], []), (['2'], []), ([True], []), ([999, '2'], []),
    ([999, 3, '2', True, 3], [3]),
    ([4, 3, 4, 999], [4, 3]),
])
def test_invalid_id_override_does_not_restore_old_selection(monkeypatch, replacement, expected):
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
            kwargs['selected_expression_ids']=replacement
        return SimpleNamespace(aborted=False,kwargs=kwargs)
    monkeypatch.setattr(selector,'_get_runtime_manager',lambda:SimpleNamespace(invoke_hook=hook))
    result=asyncio.run(selector.select_for_reply(session_id='synthetic',chat_history=[],
        reply_message=SimpleNamespace(processed_plain_text='只想吐槽'),reply_reason='倾诉',
        sub_agent_runner=AsyncMock(return_value='{"selected_ids":[2]}')))
    assert result.selected_expression_ids == expected
    assert [item['id'] for item in result.selected_expressions] == expected
    assert '合成表达2' not in result.expression_habits
    if expected:
        usage.assert_called_once_with(expected)
        for item_id in expected:
            assert f'合成表达{item_id}' in result.expression_habits
    else:
        assert result.expression_habits == ''
        usage.assert_not_called()
