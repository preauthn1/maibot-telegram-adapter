"""Execute actual chat_loop_step up to its LLM invocation, without networking."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.llm_models.model_client.openai_client import _convert_messages
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType
from src.maisaka import chat_loop_service as module


def test_preview_cancel_is_not_degraded_to_success(monkeypatch):
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
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    cancellation = asyncio.CancelledError('synthetic preview cancellation')
    preview = Mock(side_effect=cancellation)
    monkeypatch.setattr(module.PromptCLIVisualizer, 'build_prompt_section_result', preview)
    captured = []
    async def generate(*, context_factory, options):
        captured.append((_convert_messages(context_factory(None)), options))
        return generation
    generate_mock = AsyncMock(side_effect=generate)
    monkeypatch.setattr(loop, '_get_llm_chat_client', lambda kind: SimpleNamespace(generate_response_with_context=generate_mock))
    history = []
    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(loop.chat_loop_step(history, injected_user_messages=['SYNTHETIC_PROFILE'],
            tail_user_messages=['SYNTHETIC_FOCUS'], tool_definitions=[], max_context_size=12))
    assert caught.value is cancellation
    generate_mock.assert_awaited_once()
    preview.assert_called_once()
    logger.warning.assert_not_called()
    assert history == []
    assert generation.output_items == output
    assert [name for name, _ in hook_calls] == ['maisaka.planner.before_request', 'maisaka.planner.after_response']
