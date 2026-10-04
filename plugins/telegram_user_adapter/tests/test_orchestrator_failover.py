"""真实模型切换循环；网络、选模和诊断落盘隔离。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.services.llm_service import LLMServiceClient
from src.llm_models import utils_model as module
from src.llm_models.exceptions import ModelAttemptFailed
from src.llm_models.model_client.base_client import APIResponse
from src.llm_models.payload_content.context_item import ContextItemBuilder, RoleType


@pytest.mark.parametrize('all_failed', [False, True])
@pytest.mark.parametrize('real_timeout', [False, True])
@pytest.mark.parametrize('diagnostic_failure', [False, True])
def test_failover_rebuilds_context_and_excludes_failed_model(monkeypatch, all_failed, real_timeout, diagnostic_failure):
    service = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    o = service._orchestrator
    o.model_for_task = SimpleNamespace(model_list=['first', 'second'], selection_strategy='sequential', hard_timeout=0.02)
    monkeypatch.setattr(o, '_refresh_task_config', lambda: o.model_for_task)
    o.model_usage = {'first': (0, 0, 0), 'second': (0, 0, 0)}
    exclusions, contexts = [], []
    monkeypatch.setattr(module, 'ensure_configured_clients_loaded', lambda: None)
    monkeypatch.setattr(module.TempMethodsLLMUtils, 'get_model_info_by_name',
        lambda name: SimpleNamespace(name=name, api_provider=name,
            temperature=0.2 if name == 'first' else 0.4,
            max_tokens=128 if name == 'first' else 256, extra_params={'route': name}))
    monkeypatch.setattr(module.TempMethodsLLMUtils, 'get_provider_by_name',
        lambda name: SimpleNamespace(name=name, client_type='synthetic'))
    monkeypatch.setattr(module.client_registry, 'get_client_class_instance',
        lambda provider: SimpleNamespace(name=provider.name))
    original_select = o._select_model
    def select(**kwargs):
        exclusions.append(set(kwargs['exclude_models']))
        return original_select(**kwargs)
    monkeypatch.setattr(o, '_select_model', select)
    original_build = o._build_client_request
    requests = []
    def build(**kwargs):
        request = original_build(**kwargs)
        requests.append(request)
        assert request.extra_params == {'route': request.model_info.name}
        assert request.temperature == (0.2 if request.model_info.name == 'first' else 0.4)
        assert request.max_tokens == (128 if request.model_info.name == 'first' else 256)
        assert request.context_items[0].parts[0].text == 'context for ' + request.model_info.name
        return request
    monkeypatch.setattr(o, '_build_client_request', build)
    monkeypatch.setattr(module, 'has_request_snapshot', lambda exc: True)
    def update_diagnostic(*args, **kwargs):
        if diagnostic_failure:
            raise OSError('SYNTHETIC_PRIVATE_DIAGNOSTIC_MARKER')
    monkeypatch.setattr(module, 'update_failed_request_attempt', update_diagnostic)
    monkeypatch.setattr(o, '_check_slow_request', lambda *a: None)
    monkeypatch.setattr(service, '_record_cache_stats', lambda *a, **kw: None)
    output = ContextItemBuilder().set_role(RoleType.Assistant).add_text_content('fallback result').build()
    final_error = RuntimeError('synthetic exhausted')
    final_mark = Mock(side_effect=OSError('SYNTHETIC_FINAL_MARKER') if diagnostic_failure else None)
    event = Mock(side_effect=ImportError('SYNTHETIC_EVENT_MARKER') if diagnostic_failure else None)
    monkeypatch.setattr(module, 'mark_request_final_failure', final_mark)
    monkeypatch.setattr(o, '_schedule_llm_error_event', event)
    second = ModelAttemptFailed('second failed', original_exception=final_error) if all_failed else APIResponse(output_items=(output,))
    warning = Mock()
    monkeypatch.setattr(module.logger, 'warning', warning)
    # 上游异常可能包含请求正文或凭据；控制台日志只允许异常类型。
    sensitive_marker = 'SYNTHETIC_PRIVATE_REQUEST_MARKER'
    attempt = AsyncMock(side_effect=[ModelAttemptFailed(sensitive_marker), second])
    cancelled = []
    if real_timeout:
        monkeypatch.setattr(module, 'save_failed_request_snapshot', lambda **kw: 'synthetic-snapshot')
        monkeypatch.setattr(module, 'serialize_client_request_snapshot', lambda request: {})
        monkeypatch.setattr(module, 'attach_request_snapshot', lambda *a: None)
        async def timed_attempt(provider, client, *, request):
            if request.model_info.name == 'first':
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.append('first')
            assert cancelled == ['first']
            if all_failed:
                raise second
            return second
        attempt = AsyncMock(side_effect=timed_attempt)
        monkeypatch.setattr(o, '_attempt_request_on_model', attempt)
    else:
        monkeypatch.setattr(o, '_attempt_request_on_model_with_timeout', attempt)
    async def factory(client, model):
        assert client.name == model.name
        contexts.append(model.name)
        return [ContextItemBuilder().set_role(RoleType.User).add_text_content('context for ' + model.name).build()]
    if all_failed:
        with pytest.raises(RuntimeError) as caught:
            asyncio.run(service.generate_response_with_context(factory))
        assert caught.value is final_error
        assert exclusions == [set(), {'first'}]
        assert contexts == ['first', 'second']
        assert attempt.await_count == 2
        final_mark.assert_called_once_with(final_error)
        event.assert_called_once_with(model_name='second', message='模型请求失败，异常类型: RuntimeError')
        assert 'synthetic exhausted' not in str(event.call_args_list)
        assert o.model_usage == {'first': (0, 1, 0), 'second': (0, 1, 0)}
        return
    result = asyncio.run(service.generate_response_with_context(factory))
    assert sensitive_marker not in str(warning.call_args_list)
    final_mark.assert_not_called()
    event.assert_not_called()
    assert exclusions == [set(), {'first'}]
    assert contexts == ['first', 'second']
    assert attempt.await_count == 2
    assert result.response == 'fallback result'
    assert result.model_name == 'second'
    assert o.model_usage == {'first': (0, 1, 0), 'second': (0, 0, 0)}
