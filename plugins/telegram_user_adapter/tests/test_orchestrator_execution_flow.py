"""真实请求执行循环；模型选择与网络边界隔离，保留真实请求构建。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from src.llm_models.utils_model import LLMOrchestrator
from src.llm_models.model_client.base_client import APIResponse
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType
from src.services.llm_service import LLMServiceClient


def test_execute_loop_preserves_context_and_usage(monkeypatch):
    service = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    orchestrator = service._orchestrator
    assert isinstance(orchestrator, LLMOrchestrator)
    model = SimpleNamespace(name='synthetic-model', temperature=0.2, max_tokens=128, extra_params={'synthetic_option': True})
    provider, client = object(), object()
    def select_model(**kwargs):
        # 配置刷新会重建使用状态；模拟选择器在实际选中时注册该模型。
        orchestrator.model_usage['synthetic-model'] = (0, 0, 1)
        return model, provider, client
    select = Mock(side_effect=select_model)
    monkeypatch.setattr(orchestrator, '_select_model', select)
    orchestrator.model_usage['synthetic-model'] = (0, 0, 1)
    item = ContextItemBuilder().set_role(RoleType.User).add_text_content('合成任务').build()
    response = APIResponse(output_items=(ContextItemBuilder().set_role(RoleType.Assistant).add_text_content('合成回答').build(),))
    attempt = AsyncMock(return_value=response)
    monkeypatch.setattr(orchestrator, '_attempt_request_on_model_with_timeout', attempt)
    monkeypatch.setattr(orchestrator, '_check_slow_request', lambda *a: None)
    monkeypatch.setattr(service, '_record_cache_stats', lambda *a, **kw: None)
    async def factory(actual_client, actual_model):
        assert actual_client is client and actual_model is model
        return [item]
    result = asyncio.run(service.generate_response_with_context(factory))
    select.assert_called_once()
    attempt.assert_awaited_once()
    request = attempt.call_args.args[2]
    assert attempt.call_args.args[:2] == (provider, client)
    assert request.model_info is model
    assert request.context_items == [item]
    assert request.trace_context.session_id == 'synthetic'
    assert request.temperature == 0.2 and request.max_tokens == 128
    assert request.extra_params == model.extra_params
    assert request.extra_params is not model.extra_params
    assert result.response == '合成回答'
    assert result.model_name == 'synthetic-model'
    assert orchestrator.model_usage['synthetic-model'] == (0, 0, 0)
