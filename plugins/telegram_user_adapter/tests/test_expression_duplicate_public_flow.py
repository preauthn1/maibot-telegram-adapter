"""重复候选经公开入口排除，越界模型选择不得恢复冲突项。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector

@pytest.mark.parametrize('all_conflicting', [False, True])
def test_hook_duplicate_candidates_never_reach_selection(monkeypatch, all_conflicting):
    selector = MaisakaExpressionSelector()
    rows = [{'id':i,'situation':'倾诉','style':f'有效表达{i}'} for i in range(1,11)]
    monkeypatch.setattr(selector, '_can_use_expressions', lambda _: True)
    monkeypatch.setattr(selector, '_load_all_expression_candidates', lambda _: rows)
    monkeypatch.setattr(selector, '_build_expression_candidate_pool', AsyncMock(return_value=rows))
    monkeypatch.setattr(selector, '_serialize_reply_message', lambda _: {})
    usage = Mock()
    monkeypatch.setattr(selector, '_update_last_active_time', usage)
    async def hook(name, **kwargs):
        if name.endswith('before_select'):
            kwargs['candidates'] = ([dict(rows[0]),dict(rows[0],style='冲突措辞')] if all_conflicting else [*rows,dict(rows[0],style='冲突措辞')])
        return SimpleNamespace(aborted=False,kwargs=kwargs)
    monkeypatch.setattr(selector, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
    runner = AsyncMock(return_value='{"selected_ids":[1,2]}')
    result = asyncio.run(selector.select_for_reply(session_id='synthetic',chat_history=[],
        reply_message=SimpleNamespace(processed_plain_text='只想吐槽'),reply_reason='倾诉',sub_agent_runner=runner))
    if all_conflicting:
        runner.assert_not_awaited()
        assert result.selected_expression_ids == []
        assert result.expression_habits == ''
        usage.assert_not_called()
    else:
        runner.assert_awaited_once()
        prompt = runner.call_args.args[0]
        assert '\n1: 情景=' not in prompt and '冲突措辞' not in prompt
        assert '\n2: 情景=' in prompt
        assert result.selected_expression_ids == [2]
        assert '有效表达2' in result.expression_habits and '冲突措辞' not in result.expression_habits
        usage.assert_called_once_with([2])
