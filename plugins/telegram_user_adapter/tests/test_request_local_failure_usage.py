"""本地请求构建或未包装异常不应残留选模占用。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
import pytest
from src.services.llm_service import LLMServiceClient


@pytest.mark.parametrize('stage', ['build', 'attempt'])
def test_local_failure_releases_usage_without_retry(monkeypatch, stage):
    service = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    o = service._orchestrator
    error = ValueError('synthetic local failure')
    def select(**kwargs):
        o.model_usage['synthetic'] = (12, 3, 1)
        return SimpleNamespace(name='synthetic'), object(), object()
    selection = Mock(side_effect=select)
    monkeypatch.setattr(o, '_select_model', selection)
    build = Mock(side_effect=error) if stage == 'build' else Mock(return_value=object())
    monkeypatch.setattr(o, '_build_client_request', build)
    attempt = AsyncMock(side_effect=error)
    monkeypatch.setattr(o, '_attempt_request_on_model_with_timeout', attempt)
    event = Mock()
    monkeypatch.setattr(o, '_schedule_llm_error_event', event)
    with pytest.raises(ValueError) as caught:
        asyncio.run(service.generate_response_with_context(lambda client: []))
    assert caught.value is error
    selection.assert_called_once()
    event.assert_not_called()
    if stage == 'build':
        attempt.assert_not_awaited()
    else:
        attempt.assert_awaited_once()
    assert o.model_usage['synthetic'] == (12, 3, 0)
