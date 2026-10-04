"""真实分发器的失败合并策略；不启动插件进程。"""
from types import SimpleNamespace
import pytest
from src.plugin_runtime.host.hook_dispatcher import HookDispatcher, HookDispatchResult, HookHandlerExecutionResult


@pytest.mark.parametrize('policy,allowed,aborted', [('skip', True, False), ('abort', True, True), ('abort', False, False)])
def test_failed_handler_does_not_commit_modified_kwargs(policy, allowed, aborted):
    dispatcher = object.__new__(HookDispatcher)
    target = SimpleNamespace(entry=SimpleNamespace(error_policy=policy, full_name='synthetic.handler'))
    spec = SimpleNamespace(allow_abort=allowed, allow_kwargs_mutation=True)
    original = {'selected_expression_ids': [1]}
    result = HookDispatchResult(hook_name='expression.select.after_selection', kwargs=original.copy())
    execution = HookHandlerExecutionResult(handler_name='synthetic.handler', plugin_id='synthetic',
        success=False, modified_kwargs={'selected_expression_ids': [2]}, error_message='synthetic failure')
    dispatcher._merge_blocking_result(spec, target, execution, result)
    assert result.aborted is aborted
    assert result.kwargs == original
    assert result.errors == ['synthetic failure']
