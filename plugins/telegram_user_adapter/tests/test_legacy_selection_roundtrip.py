"""生产 legacy 采样到最终选择；仅隔离数据库、插件和模型调用。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector


import pytest


@pytest.mark.parametrize('action', ['keep', 'abort', 'clear', 'replace_ids', 'invalid_ids', 'clear_expressions', 'inplace_clear', 'inplace_style', 'hook_error', 'dispatch_skip', 'dispatch_abort'])
def test_legacy_pool_reaches_runner_and_only_selection_is_recorded(monkeypatch, action):
    selector = object.__new__(MaisakaExpressionSelector)
    candidates = [dict(id=i, situation=f'情境{i}', style=f'表达{i}', count=2) for i in range(1, 13)]
    monkeypatch.setattr(selector, '_can_use_expressions', lambda _: True)
    monkeypatch.setattr(selector, '_load_all_expression_candidates', lambda _: candidates)
    monkeypatch.setattr(selector, '_use_vector_candidate_pool', lambda: False)
    monkeypatch.setattr(selector, '_build_chat_info', lambda _: '')
    monkeypatch.setattr(selector, '_serialize_reply_message', lambda _: {})
    observed = {}
    async def hook(name, **kwargs):
        if name == 'expression.select.before_select':
            observed['ids'] = [c['id'] for c in kwargs['candidates']]
        if name == 'expression.select.after_selection':
            update.assert_not_called()
            if action in ('dispatch_skip', 'dispatch_abort'):
                from src.plugin_runtime.host.hook_dispatcher import HookDispatcher, HookDispatchResult, HookHandlerExecutionResult
                dispatcher = object.__new__(HookDispatcher)
                dispatch = HookDispatchResult(hook_name=name, kwargs=kwargs)
                target = SimpleNamespace(entry=SimpleNamespace(
                    error_policy='abort' if action == 'dispatch_abort' else 'skip', full_name='synthetic.handler'))
                execution = HookHandlerExecutionResult(handler_name='synthetic.handler', plugin_id='synthetic',
                    success=False, modified_kwargs={'selected_expression_ids': [999999]}, error_message='synthetic failure')
                dispatcher._merge_blocking_result(SimpleNamespace(allow_abort=True, allow_kwargs_mutation=True),
                    target, execution, dispatch)
                assert dispatch.errors == ['synthetic failure']
                return dispatch
            if action == 'hook_error':
                raise RuntimeError('synthetic hook failure')
            if action == 'abort':
                return SimpleNamespace(aborted=True, kwargs=kwargs)
            if action == 'clear':
                kwargs['selected_expression_ids'] = []
            elif action == 'clear_expressions':
                kwargs['selected_expressions'] = []
            elif action == 'inplace_clear':
                kwargs['selected_expressions'].clear()
            elif action == 'inplace_style':
                kwargs['selected_expressions'][0]['style'] = '合成替换风格'
            elif action == 'replace_ids':
                kwargs['selected_expression_ids'] = [observed['ids'][0]]
            elif action == 'invalid_ids':
                kwargs['selected_expression_ids'] = [999999]
        return SimpleNamespace(aborted=False, kwargs=kwargs)
    monkeypatch.setattr(selector, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
    update = Mock()
    monkeypatch.setattr(selector, '_update_last_active_time', update)
    async def choose(prompt):
        assert len(observed['ids']) == len(set(observed['ids'])) == 10
        for i in observed['ids']:
            assert f'{i}: 情景=情境{i} | 风格=表达{i}' in prompt
        return '{"selected_ids":[' + str(observed['ids'][-1]) + ']}'
    runner = AsyncMock(side_effect=choose)
    def run_selection():
        return asyncio.run(selector.select_for_reply(session_id='synthetic', chat_history=[],
            reply_message=SimpleNamespace(processed_plain_text='合成目标'), reply_reason='合成理由',
            sub_agent_runner=runner))
    if action == 'hook_error':
        with pytest.raises(RuntimeError, match='synthetic hook failure'):
            run_selection()
        runner.assert_awaited_once()
        update.assert_not_called()
        return
    result = run_selection()
    runner.assert_awaited_once()
    # 显式无效ID覆盖现在按空选择处理；失败Hook的skip仍保留原选择。
    if action in ('abort', 'clear', 'clear_expressions', 'inplace_clear', 'dispatch_abort', 'invalid_ids'):
        assert result.selected_expression_ids == []
        assert result.selected_expressions == []
        assert not result.expression_habits
        update.assert_not_called()
        return
    chosen = observed['ids'][0] if action == 'replace_ids' else observed['ids'][-1]
    assert result.selected_expression_ids == [chosen]
    assert [c['id'] for c in result.selected_expressions] == [chosen]
    if action == 'inplace_style':
        assert '合成替换风格' in result.expression_habits
        assert all(c['style'] == f"表达{c['id']}" for c in candidates)
    else:
        assert f'表达{chosen}' in result.expression_habits
    update.assert_called_once_with([chosen])
    assert len(candidates) == 12
