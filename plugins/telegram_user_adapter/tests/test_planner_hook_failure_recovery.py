"""Actual request/loop recover after a failed before-request hook."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.maisaka.runtime import PlannerInterruptController
from src.maisaka.reasoning_engine import MaisakaReasoningEngine

@pytest.mark.parametrize('error_type', [OSError, ValueError])
def test_hook_failure_then_retry(monkeypatch, error_type):
    loop = object.__new__(MaisakaChatLoopService)
    loop._is_group_chat = False
    loop._session_id = 'synthetic'
    loop._custom_chat_system_prompt = 'synthetic system'
    loop._interrupt_flag = None
    monkeypatch.setattr(loop, '_resolve_enable_visual_message', lambda kind: False)
    for name in ('_build_current_chat_attention_tail_message', '_build_current_time_user_message', '_build_planner_final_user_reminder'):
        monkeypatch.setattr(loop, name, lambda: '')
    original = error_type('synthetic hook failure')
    hook = AsyncMock(side_effect=original)
    monkeypatch.setattr(loop, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
    reached = OSError('synthetic LLM boundary stop')
    generate = AsyncMock(side_effect=reached)
    monkeypatch.setattr(loop, '_get_llm_chat_client', lambda kind: SimpleNamespace(generate_response_with_context=generate))
    controller = PlannerInterruptController()
    engine = object.__new__(MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(_bind_planner_interrupt_flag=controller.bind,
        _unbind_planner_interrupt_flag=controller.unbind, _chat_loop_service=loop,
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic-turn'
    async def scenario():
        with pytest.raises(error_type) as caught:
            await engine._run_interruptible_planner(tool_definitions=[])
        assert caught.value is original
        generate.assert_not_awaited()
        assert loop._interrupt_flag is None
        assert controller.request(max_consecutive_count=3) == 'idle'
        async def recovered(name, **kwargs):
            assert name == 'maisaka.planner.before_request'
            return SimpleNamespace(kwargs=kwargs)
        hook.side_effect = recovered
        with pytest.raises(OSError) as caught:
            await engine._run_interruptible_planner(tool_definitions=[])
        assert caught.value is reached
        generate.assert_awaited_once()
        assert hook.await_count == 2
        assert loop._interrupt_flag is None
        assert controller.request(max_consecutive_count=3) == 'idle'
        assert controller.consecutive_count == 0
        assert engine._runtime._chat_history == []
    asyncio.run(scenario())
