"""Cancellation during before_request stops before LLM and clears real flags."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.maisaka import chat_loop_service as module
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType
from src.maisaka.runtime import PlannerInterruptController
from src.maisaka.reasoning_engine import MaisakaReasoningEngine


def test_after_hook_cancel_cleans_real_request_state(monkeypatch):
    loop = object.__new__(MaisakaChatLoopService)
    loop._is_group_chat = False
    loop._session_id = 'synthetic'
    loop._custom_chat_system_prompt = 'synthetic system'
    loop._interrupt_flag = None
    monkeypatch.setattr(loop, '_resolve_enable_visual_message', lambda kind: False)
    monkeypatch.setattr(loop, '_build_current_chat_attention_tail_message', lambda: '')
    monkeypatch.setattr(loop, '_build_current_time_user_message', lambda: '')
    monkeypatch.setattr(loop, '_build_planner_final_user_reminder', lambda: '')
    output = (ContextItemBuilder().set_role(RoleType.Assistant).add_text_content('synthetic reply').build(),)
    generation = SimpleNamespace(output_items=output, prompt_tokens=10, completion_tokens=3,
        total_tokens=13, model_name='synthetic', generation_attempts=[])
    generate = AsyncMock(return_value=generation)
    monkeypatch.setattr(loop, '_log_prompt_cache_usage', lambda **kw: None)
    preview = Mock()
    monkeypatch.setattr(module.PromptCLIVisualizer, 'build_prompt_section_result', preview)
    monkeypatch.setattr(loop, '_get_llm_chat_client', lambda kind: SimpleNamespace(generate_response_with_context=generate))
    controller = PlannerInterruptController()
    engine = object.__new__(MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(_bind_planner_interrupt_flag=controller.bind,
        _unbind_planner_interrupt_flag=controller.unbind, _chat_loop_service=loop,
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic-turn'

    async def scenario():
        entered, cleaned = asyncio.Event(), asyncio.Event()
        async def hook(name, **kwargs):
            if name == 'maisaka.planner.before_request':
                return SimpleNamespace(kwargs=kwargs)
            assert name == 'maisaka.planner.after_response'
            assert controller._flag is loop._interrupt_flag
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        monkeypatch.setattr(loop, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
        task = asyncio.create_task(engine._run_interruptible_planner(
            injected_user_messages=['synthetic profile'], tool_definitions=[]))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert task.cancelled() and cleaned.is_set()
            assert loop._interrupt_flag is None
            assert controller.request(max_consecutive_count=3) == 'idle'
            assert controller.consecutive_count == 0
            generate.assert_awaited_once()
            preview.assert_not_called()
            assert engine._runtime._chat_history == []
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
