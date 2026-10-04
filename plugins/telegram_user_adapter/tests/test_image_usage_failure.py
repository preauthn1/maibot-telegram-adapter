"""图像生成入口：统计故障不丢失成功响应；不测试图像编码或网络。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.services.llm_service import LLMServiceClient
from src.llm_models import utils_model as module
from src.llm_models.model_client.base_client import APIResponse, UsageRecord
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType


@pytest.mark.parametrize('entry', ['image', 'text'])
@pytest.mark.parametrize('storage_failure', [False, True])
def test_image_entry_preserves_response_and_usage(monkeypatch, storage_failure, entry):
    o = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')._orchestrator
    output = ContextItemBuilder().set_role(RoleType.Assistant).add_text_content('合成图像回答').build()
    usage = UsageRecord('synthetic-model', 'synthetic-provider', 13, 7, 20)
    execute = AsyncMock(return_value=SimpleNamespace(
        api_response=APIResponse(output_items=(output,), usage=usage),
        model_info=SimpleNamespace(name='synthetic-model')))
    monkeypatch.setattr(o, '_execute_request', execute)
    monkeypatch.setattr(o, '_check_slow_request', lambda *args: None)
    recorder = Mock(side_effect=OSError('SYNTHETIC_PRIVATE_STORAGE') if storage_failure else None)
    warning = Mock()
    monkeypatch.setattr(module.llm_usage_recorder, 'record_usage_to_database', recorder)
    monkeypatch.setattr(module.logger, 'warning', warning)
    if entry == 'image':
        result = asyncio.run(o.generate_response_for_image(
            '合成图像问题', '', 'png', session_id='synthetic'))
    else:
        result = asyncio.run(o.generate_response_async('合成问题', session_id='synthetic'))
    execute.assert_awaited_once()
    recorder.assert_called_once()
    assert recorder.call_args.kwargs['model_usage'] is usage
    assert recorder.call_args.kwargs['session_id'] == 'synthetic'
    assert result.output_items == (output,)
    assert result.response == '合成图像回答'
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == (13, 7, 20)
    assert warning.call_count == int(storage_failure)
    assert 'SYNTHETIC_PRIVATE_STORAGE' not in str(warning.call_args_list)
    if storage_failure:
        assert 'OSError' in str(warning.call_args_list)
