"""Execute actual chat_loop_step up to its LLM invocation, without networking."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.maisaka import chat_loop_service as module
from src.llm_models.model_client.openai_client import _convert_messages


def test_real_decoder_failure_preserves_original_batch(monkeypatch):
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
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    decoder = Mock(wraps=module.deserialize_prompt_items)
    monkeypatch.setattr(module, 'deserialize_prompt_items', decoder)
    hook_calls = []
    async def hook(name, **kwargs):
        hook_calls.append((name, kwargs))
        # Valid leading replacement must not leak if a later item fails.
        updated = loop._build_request_messages([], enable_visual_message=False,
            injected_user_messages=['PARTIAL_REPLACEMENT_SENTINEL'], system_prompt='SYNTHETIC_SYSTEM')
        raw = module.serialize_prompt_items(updated)
        raw.append({'type': 'PRIVATE_PROFILE_SENTINEL'})
        return SimpleNamespace(kwargs=dict(kwargs, items=raw))
    monkeypatch.setattr(loop, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
    stop = OSError('synthetic boundary stop')
    captured = []
    async def generate(*, context_factory, options):
        captured.append((_convert_messages(context_factory(None)), options))
        raise stop
    generate_mock = AsyncMock(side_effect=generate)
    monkeypatch.setattr(loop, '_get_llm_chat_client', lambda kind: SimpleNamespace(generate_response_with_context=generate_mock))
    history = []
    with pytest.raises(OSError) as caught:
        asyncio.run(loop.chat_loop_step(history, injected_user_messages=['SYNTHETIC_PROFILE'],
            tail_user_messages=['SYNTHETIC_FOCUS'], tool_definitions=[], max_context_size=12))
    assert caught.value is stop
    generate_mock.assert_awaited_once()
    assert len(hook_calls) == 1 and hook_calls[0][0] == 'maisaka.planner.before_request'
    assert captured[0][0] == [
        {'role': 'system', 'content': 'SYNTHETIC_SYSTEM'},
        *({'role': 'user', 'content': text} for text in [
            'SYNTHETIC_PROFILE', 'SYNTHETIC_TIME', 'SYNTHETIC_FOCUS', 'SYNTHETIC_ATTENTION', 'SYNTHETIC_FINAL']),
    ]
    assert captured[0][1].interrupt_flag is flag
    assert captured[0][1].tool_options is None
    assert history == []

    decoder.assert_called_once()
    logger.warning.assert_called_once()
    assert 'PRIVATE_PROFILE_SENTINEL' not in str(logger.mock_calls)
    assert 'error_type=' in str(logger.mock_calls)
    assert 'PARTIAL_REPLACEMENT_SENTINEL' not in str(captured[0][0])
