"""Execute actual chat_loop_step up to its LLM invocation, without networking."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.llm_models.model_client.openai_client import _convert_messages
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType
from src.maisaka import chat_loop_service as module


@pytest.mark.parametrize('replacement', ['SYNTHETIC_UPDATED_REPLY', ''])
def test_after_hook_valid_output_reaches_response(monkeypatch, replacement):
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
        if name == 'maisaka.planner.after_response':
            updated = [ContextItemBuilder().set_role(RoleType.Assistant).add_text_content(replacement).build()] if replacement else []
            return SimpleNamespace(kwargs=dict(kwargs, output_items=module.serialize_prompt_items(updated)))
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
    history = []
    response = asyncio.run(loop.chat_loop_step(history, injected_user_messages=['SYNTHETIC_PROFILE'],
        tail_user_messages=['SYNTHETIC_FOCUS'], tool_definitions=[], max_context_size=12))
    assert response.content == (replacement or None)
    assert _convert_messages(list(response.output_items)) == ([{'role': 'assistant', 'content': replacement}] if replacement else [])
    assert generation.output_items == output
    assert _convert_messages(list(output)) == [{'role': 'assistant', 'content': 'SYNTHETIC_REPLY'}]
    assert (response.prompt_tokens, response.completion_tokens, response.total_tokens) == (10, 3, 13)
    assert response.model_name == 'synthetic-model'
    assert _convert_messages(response.request_messages) == captured[0][0]
    generate_mock.assert_awaited_once()
    assert [name for name, _ in hook_calls] == ['maisaka.planner.before_request', 'maisaka.planner.after_response']
    assert captured[0][0] == [
        {'role': 'system', 'content': 'SYNTHETIC_SYSTEM'},
        *({'role': 'user', 'content': text} for text in [
            'SYNTHETIC_PROFILE', 'SYNTHETIC_TIME', 'SYNTHETIC_FOCUS', 'SYNTHETIC_ATTENTION', 'SYNTHETIC_FINAL']),
    ]
    assert captured[0][1].interrupt_flag is flag
    assert captured[0][1].tool_options is None
    assert history == []
