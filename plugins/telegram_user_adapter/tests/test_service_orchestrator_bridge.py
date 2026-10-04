"""真实服务门面与调度器响应装配；仅请求执行与统计隔离。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.services.llm_service import LLMServiceClient
from src.llm_models.utils_model import LLMOrchestrator
from src.llm_models.model_client.base_client import APIResponse, UsageRecord
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType


@pytest.mark.parametrize('answer', ['Alpine', '{"ok":true}', '```html\n<div>你好</div>\n```'])
@pytest.mark.parametrize('with_usage', [False, True, 'storage_failure'])
def test_real_orchestrator_response_assembly(monkeypatch, answer, with_usage):
    client = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    assert isinstance(client._orchestrator, LLMOrchestrator)
    monkeypatch.setattr(client, '_record_cache_stats', lambda *a, **kw: None)
    monkeypatch.setattr(client._orchestrator, '_check_slow_request', lambda *a: None)
    item = ContextItemBuilder().set_role(RoleType.User).add_text_content('合成请求').build()
    output = ContextItemBuilder().set_role(RoleType.Assistant).add_text_content(answer).build()
    usage = UsageRecord(model_name='synthetic-model', provider_name='synthetic',
                        prompt_tokens=13, completion_tokens=7, total_tokens=20) if with_usage else None
    from src.llm_models import utils_model as runtime_module
    from unittest.mock import Mock
    recorder = Mock(side_effect=OSError('synthetic storage failure') if with_usage == 'storage_failure' else None)
    monkeypatch.setattr(runtime_module.llm_usage_recorder, 'record_usage_to_database', recorder)
    async def execute(**kwargs):
        assert kwargs['session_id'] == 'synthetic'
        items = await kwargs['context_factory'](SimpleNamespace(), SimpleNamespace(name='synthetic'))
        assert items == [item]
        return SimpleNamespace(api_response=APIResponse(output_items=(output,), usage=usage),
                               model_info=SimpleNamespace(name='synthetic-model'))
    request = AsyncMock(side_effect=execute)
    monkeypatch.setattr(client._orchestrator, '_execute_request', request)
    async def context_factory(client, model_info):
        assert model_info.name == 'synthetic'
        return [item]
    from src.llm_models import utils_model as module
    from unittest.mock import Mock
    debug = Mock()
    monkeypatch.setattr(module.logger, 'debug', debug)
    result = asyncio.run(client.generate_response_with_context(context_factory))
    logged = '\n'.join(str(call.args[0]) for call in debug.call_args_list)
    assert answer not in logged
    assert repr(answer)[1:-1] not in logged
    assert 'APIResponse(' not in logged
    assert 'LLM响应已返回，输出项数: 1' in logged
    request.assert_awaited_once()
    assert result.response == answer
    assert result.output_items == (output,)
    assert result.model_name == 'synthetic-model'
    assert (result.prompt_tokens, result.completion_tokens, result.total_tokens) == ((13, 7, 20) if with_usage else (0, 0, 0))
    assert recorder.call_count == (1 if with_usage else 0)
