"""生产表达选择包装器继承父上下文；不启动实际子代理。"""
import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock
from src.maisaka.builtin_tool.reply import _run_expression_selector
from src.maisaka.runtime import MaisakaHeartFlowChatting


def test_expression_runner_keeps_parent_context_contract():
    runner = AsyncMock(return_value=SimpleNamespace(content=' {"selected_ids":[]} '))
    ctx = SimpleNamespace(runtime=SimpleNamespace(run_sub_agent=runner))
    result = asyncio.run(_run_expression_selector(ctx, 'synthetic selector prompt'))
    assert result == '{"selected_ids":[]}'
    runner.assert_awaited_once_with(context_message_limit=10,
        system_prompt='synthetic selector prompt', request_kind='expression_selector')
    signature = inspect.signature(MaisakaHeartFlowChatting.run_sub_agent)
    assert signature.parameters['include_parent_context'].default is True
    assert signature.parameters['model_task_name'].default == 'planner'
