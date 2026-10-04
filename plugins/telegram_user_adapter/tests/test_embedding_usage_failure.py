"""向量统计故障不能制造检索失败；空向量仍须失败。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.services.llm_service import LLMServiceClient
from src.llm_models import utils_model as module
from src.llm_models.model_client.base_client import APIResponse, UsageRecord

@pytest.mark.parametrize('empty', [False, True])
def test_embedding_survives_usage_error(monkeypatch, empty):
    orchestrator = LLMServiceClient('replyer', request_type='synthetic')._orchestrator
    response = APIResponse(embedding=[] if empty else [0.25, 0.75], usage=UsageRecord('m','p',2,0,2))
    execute = AsyncMock(return_value=SimpleNamespace(api_response=response, model_info=SimpleNamespace(name='m', model_identifier='m', api_provider='p')))
    monkeypatch.setattr(orchestrator, '_execute_request', execute)
    monkeypatch.setattr(module.llm_usage_recorder, 'record_usage_to_database', Mock(side_effect=OSError('PRIVATE_STORAGE')))
    warning = Mock()
    monkeypatch.setattr(module.logger, 'warning', warning)
    if empty:
        with pytest.raises(RuntimeError, match='获取embedding失败'):
            asyncio.run(orchestrator.get_embedding('synthetic'))
    else:
        result = asyncio.run(orchestrator.get_embedding('synthetic'))
        assert result.embedding == [0.25, 0.75]
    execute.assert_awaited_once()
    assert warning.call_count == 1
    assert 'PRIVATE_STORAGE' not in str(warning.call_args_list)
