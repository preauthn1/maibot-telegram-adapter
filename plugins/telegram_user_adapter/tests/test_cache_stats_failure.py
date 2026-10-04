"""缓存统计持久化失败不丢弃已生成的响应。"""
import asyncio
import pytest
from unittest.mock import AsyncMock, Mock
from src.services import llm_service as module
from src.services.llm_service import LLMServiceClient
from src.llm_models.model_client.base_client import APIResponse
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType


@pytest.mark.parametrize('stage', ['storage', 'serialization'])
def test_cache_storage_failure_preserves_response(monkeypatch, stage):
    client = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    output = ContextItemBuilder().set_role(RoleType.Assistant).add_text_content('保留回答').build()
    result = client._orchestrator._build_generation_result(APIResponse(output_items=(output,)), 'synthetic')
    generate = AsyncMock(return_value=result)
    monkeypatch.setattr(client._orchestrator, 'generate_response_with_context_async', generate)
    recorder = Mock(side_effect=OSError('SYNTHETIC_PRIVATE_CACHE'))
    monkeypatch.setattr(module, 'record_llm_cache_usage', recorder)
    if stage == 'serialization':
        result.request_wire_payload = {'synthetic': True}
        monkeypatch.setattr(client, '_sanitize_wire_value_for_cache_stats',
                            Mock(side_effect=ValueError('SYNTHETIC_PRIVATE_CACHE')))
    warning = Mock()
    monkeypatch.setattr(module.logger, 'warning', warning)
    actual = asyncio.run(client.generate_response_with_context(lambda c: []))
    assert actual is result
    assert actual.response == '保留回答'
    assert recorder.call_count == (1 if stage == 'storage' else 0)
    warning.assert_called_once()
    assert 'SYNTHETIC_PRIVATE_CACHE' not in str(warning.call_args_list)
    generate.assert_awaited_once()
