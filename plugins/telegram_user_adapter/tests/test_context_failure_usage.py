"""上下文构建失败或取消不应残留模型占用。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.services.llm_service import LLMServiceClient

@pytest.mark.parametrize('error', [ValueError('synthetic'), asyncio.CancelledError()])
def test_context_failure_releases_usage(monkeypatch, error):
    service = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    o = service._orchestrator
    def select(**kwargs):
        o.model_usage['synthetic'] = (12, 3, 1)
        return SimpleNamespace(name='synthetic'), object(), object()
    monkeypatch.setattr(o, '_select_model', select)
    attempt = AsyncMock()
    monkeypatch.setattr(o, '_attempt_request_on_model_with_timeout', attempt)
    async def factory(client, model):
        raise error
    with pytest.raises(type(error)) as caught:
        asyncio.run(service.generate_response_with_context(factory))
    assert caught.value is error
    attempt.assert_not_awaited()
    assert o.model_usage['synthetic'] == (12, 3, 0)
