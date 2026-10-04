"""Execute actual chat_loop_step up to its LLM invocation, without networking."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.llm_models.model_client.openai_client import _convert_messages
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType
from src.maisaka import chat_loop_service as module


def test_cancelled_turn_leaves_shared_generation_reusable(monkeypatch):
    loop = object.__new__(MaisakaChatLoopService)
    loop._is_group_chat = False
    loop._session_id = 'synthetic-session'
    loop._custom_chat_system_prompt = 'SYNTHETIC_SYSTEM'
    flag = asyncio.Event()
    loop.set_interrupt_flag(flag)
    monkeypatch.setattr(loop, '_resolve_enable_visual_message', lambda kind: False)
    monkeypatch.setattr(loop, '_build_current_chat_attention_tail_message', lambda: 'SYNTHETIC_ATTENTION')
    monkeypatch.setattr(loop, '_build_current_time_user_message', lambda: 'SYNTHETIC_TIME')
    monkeypatch.setattr(loop, '_build_planner_final_user_reminder', lambda: 'SYNTHETIC_FINAL')
    hook_calls = []
    async def hook(name, **kwargs):
        hook_calls.append((name, kwargs))
        return SimpleNamespace(kwargs=kwargs)
    monkeypatch.setattr(loop, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
    output = (ContextItemBuilder().set_role(RoleType.Assistant).add_text_content('SYNTHETIC_REPLY').build(),)
    generation = SimpleNamespace(output_items=output, prompt_tokens=10, completion_tokens=3,
        total_tokens=13, model_name='synthetic-model', generation_attempts=[])
    monkeypatch.setattr(loop, '_log_prompt_cache_usage', lambda **kw: None)
    monkeypatch.setattr(module.PromptCLIVisualizer, 'build_prompt_section_result',
        lambda *a, **kw: SimpleNamespace(preview_access=SimpleNamespace(preview_web_uri=None), panel=None))
    captured = []
    async def generate(*, context_factory, options):
        captured.append((_convert_messages(context_factory(None)), options))
        return generation
    generate_mock = AsyncMock(side_effect=generate)
    monkeypatch.setattr(loop, '_get_llm_chat_client', lambda kind: SimpleNamespace(generate_response_with_context=generate_mock))
    async def scenario():
        entered = asyncio.Event()
        cleaned = asyncio.Event()
        async def blocking_hook(name, **kwargs):
            if name == 'maisaka.planner.after_response':
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cleaned.set()
            return SimpleNamespace(kwargs=kwargs)
        monkeypatch.setattr(loop, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=blocking_hook))
        history = []
        task = asyncio.create_task(loop.chat_loop_step(history, tool_definitions=[],
            logical_turn_id='synthetic-cancelled-turn'))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert task.cancelled()
            assert cleaned.is_set()
            assert generation.output_items is output
            assert output[0].meta.logical_turn_id is None
            assert history == []
            monkeypatch.setattr(loop, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
            response = await asyncio.wait_for(loop.chat_loop_step(history, tool_definitions=[],
                logical_turn_id='synthetic-next-turn'), 2)
            assert response.content == 'SYNTHETIC_REPLY'
            assert response.output_items[0].meta.logical_turn_id == 'synthetic-next-turn'
            assert response.output_items[0].meta.item_id == output[0].meta.item_id
            assert generation.output_items is output
            assert output[0].meta.logical_turn_id is None
            assert (response.prompt_tokens, response.completion_tokens, response.total_tokens) == (10, 3, 13)
            assert generate_mock.await_count == 2
            assert history == []
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
