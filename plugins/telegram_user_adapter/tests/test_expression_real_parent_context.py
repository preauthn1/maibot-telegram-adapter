"""真实包装器、runtime与父历史筛选，模型执行边界截获。"""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from src.maisaka.builtin_tool.reply import _run_expression_selector
from src.maisaka import runtime as module
from src.maisaka.context.messages import SessionBackedMessage
from src.common.data_models.message_component_data_model import MessageSequence
from src.chat.replyer.maisaka_expression_selector import MaisakaExpressionSelector


def test_expression_runtime_passes_parent_context_and_guard(monkeypatch):
    runtime = object.__new__(module.MaisakaHeartFlowChatting)
    runtime.session_id = 'synthetic'
    runtime.chat_stream = SimpleNamespace(is_group_session=True)
    seq = MessageSequence([])
    seq.text('现在只想吐槽，不要建议')
    message = SessionBackedMessage(raw_message=seq, visible_text='现在只想吐槽，不要建议', timestamp=datetime(2026,1,1), message_id='synthetic-parent')
    runtime._chat_history = [message]
    captured = {}
    real = module.MaisakaChatLoopService
    step = AsyncMock(return_value=SimpleNamespace(content=' {"selected_ids":[]} '))
    class CapturedService:
        select_llm_context_messages = staticmethod(real.select_llm_context_messages)
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def set_interrupt_flag(self, flag):
            captured['interrupt_flag'] = flag
        chat_loop_step = step
    monkeypatch.setattr(module, 'MaisakaChatLoopService', CapturedService)
    prompt = MaisakaExpressionSelector()._build_selector_prompt(candidates=[], target_message=message.visible_text)
    result = asyncio.run(_run_expression_selector(SimpleNamespace(runtime=runtime), prompt))
    assert result == '{"selected_ids":[]}'
    assert captured['model_task_name'] == 'planner'
    assert captured['chat_system_prompt'] == prompt
    assert '拒绝要求虚构个人亲历' in prompt
    step.assert_awaited_once()
    assert step.call_args.args[0] == [message]
    assert step.call_args.kwargs['request_kind'] == 'expression_selector'
    assert step.call_args.kwargs['tool_definitions'] == []
    assert step.call_args.kwargs['max_context_size'] == 10
    assert runtime._chat_history == [message]
