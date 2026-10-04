"""成功响应后的诊断故障不应导致重复付费请求。"""
import asyncio
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace
import pytest
from src.services.llm_service import LLMServiceClient
from src.config.model_configs import ModelInfo, APIProvider
from src.llm_models import utils_model as module

@pytest.mark.parametrize('failed_step', ['record', 'mark'])
def test_success_survives_diagnostic_failure(monkeypatch, failed_step):
    o = LLMServiceClient('replyer')._orchestrator
    response = module.APIResponse(output_items=())
    client = SimpleNamespace(get_response=AsyncMock(return_value=response))
    request = module.ResponseRequest(model_info=ModelInfo(name='synthetic', model_identifier='synthetic', api_provider='synthetic'), context_items=[])
    record = Mock(side_effect=OSError('SYNTHETIC_PRIVATE') if failed_step == 'record' else None)
    mark = Mock(side_effect=OSError('SYNTHETIC_PRIVATE') if failed_step == 'mark' else None)
    monkeypatch.setattr(o, '_record_success_generation_attempt', record)
    monkeypatch.setattr(module, 'mark_request_succeeded', mark)
    monkeypatch.setattr(module, 'has_request_snapshot', lambda exc: True)
    warning = Mock()
    monkeypatch.setattr(module.logger, 'warning', warning)
    result = asyncio.run(o._attempt_request_on_model(APIProvider(max_retry=2, auth_type='none', name='synthetic', base_url='https://synthetic.invalid'), client, request))
    assert result is response
    client.get_response.assert_awaited_once()
    record.assert_called_once()
    mark.assert_called_once()
    assert 'SYNTHETIC_PRIVATE' not in str(warning.call_args_list)
    assert 'OSError' in str(warning.call_args_list)
