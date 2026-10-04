"""Execute actual chat_loop_step up to its LLM invocation, without networking."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.llm_models.model_client.openai_client import _convert_messages
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType
from src.maisaka import chat_loop_service as module


@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
def test_concurrent_shared_generation_turns(monkeypatch, order):
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
        entered = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        counter = 0
        async def gated_hook(name, **kwargs):
            nonlocal counter
            if name == 'maisaka.planner.after_response':
                index = counter
                counter += 1
                entered[index].set()
                await release[index].wait()
            return SimpleNamespace(kwargs=kwargs)
        monkeypatch.setattr(loop, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=gated_hook))
        tasks = []
        responses = {}
        try:
            for index in range(2):
                tasks.append(asyncio.create_task(loop.chat_loop_step([], tool_definitions=[],
                    injected_user_messages=[f'synthetic profile {index}'], logical_turn_id=f'synthetic-turn-{index}')))
                await asyncio.wait_for(entered[index].wait(), 2)
            assert generation.output_items is output
            assert output[0].meta.logical_turn_id is None
            for index in order:
                release[index].set()
                responses[index] = await asyncio.wait_for(tasks[index], 2)
                assert responses[index].output_items[0].meta.logical_turn_id == f'synthetic-turn-{index}'
                assert responses[index].content == 'SYNTHETIC_REPLY'
                assert generation.output_items is output
            for index, response in responses.items():
                assert response.output_items[0].meta.logical_turn_id == f'synthetic-turn-{index}'
                assert response.output_items[0].meta.item_id == output[0].meta.item_id
                wire = _convert_messages(response.request_messages)
                assert wire[1]['content'] == f'synthetic profile {index}'
            assert output[0].meta.logical_turn_id is None
            assert generate_mock.await_count == 2
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(scenario())
