"""Concurrent actual chat-loop calls keep their own flags and contexts."""
import asyncio
from types import SimpleNamespace
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.llm_models.model_client.openai_client import _convert_messages

@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
def test_concurrent_flags_and_contexts(monkeypatch, order):
    loop = object.__new__(MaisakaChatLoopService)
    loop._is_group_chat = False
    loop._session_id = 'synthetic'
    loop._custom_chat_system_prompt = 'synthetic system'
    monkeypatch.setattr(loop, '_resolve_enable_visual_message', lambda kind: False)
    monkeypatch.setattr(loop, '_build_current_chat_attention_tail_message', lambda: '')
    monkeypatch.setattr(loop, '_build_current_time_user_message', lambda: '')
    monkeypatch.setattr(loop, '_build_planner_final_user_reminder', lambda: '')

    async def scenario():
        flags = [asyncio.Event(), asyncio.Event()]
        entered = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        tasks = []
        captured = {}
        stops = [OSError('synthetic zero'), OSError('synthetic one')]
        counter = 0
        async def hook(name, **kwargs):
            nonlocal counter
            index = counter
            counter += 1
            entered[index].set()
            await release[index].wait()
            return SimpleNamespace(kwargs=kwargs)
        async def generate(*, context_factory, options):
            wire = _convert_messages(context_factory(None))
            index = 0 if wire[1]['content'] == 'synthetic profile 0' else 1
            captured[index] = (wire, options.interrupt_flag)
            raise stops[index]
        monkeypatch.setattr(loop, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
        monkeypatch.setattr(loop, '_get_llm_chat_client', lambda kind: SimpleNamespace(generate_response_with_context=generate))
        try:
            for index in range(2):
                loop.set_interrupt_flag(flags[index])
                tasks.append(asyncio.create_task(loop.chat_loop_step([], tool_definitions=[],
                    injected_user_messages=[f'synthetic profile {index}'])))
                await asyncio.wait_for(entered[index].wait(), 2)
            flags[0].set()
            for index in order:
                release[index].set()
                with pytest.raises(OSError) as caught:
                    await asyncio.wait_for(tasks[index], 2)
                assert caught.value is stops[index]
                wire, flag = captured[index]
                assert flag is flags[index]
                assert flag.is_set() == (index == 0)
                assert wire == [{'role': 'system', 'content': 'synthetic system'},
                                {'role': 'user', 'content': f'synthetic profile {index}'}]
            assert loop._interrupt_flag is flags[1]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(scenario())
