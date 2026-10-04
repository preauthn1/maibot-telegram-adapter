"""真实 wait_for 超时取消；不发网络请求，不落诊断快照。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.services.llm_service import LLMServiceClient
from src.llm_models import utils_model as module
from src.llm_models.exceptions import LLMTaskTimeoutError


def test_hard_timeout_cancels_pending_attempt(monkeypatch):
    service = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    o = service._orchestrator
    monkeypatch.setattr(o, 'model_for_task', SimpleNamespace(hard_timeout=0.02))
    state = []
    async def pending(*args, **kwargs):
        state.append('started')
        try:
            await asyncio.Event().wait()
        finally:
            state.append('cancelled')
    monkeypatch.setattr(o, '_attempt_request_on_model', pending)
    snapshot = Mock(return_value='synthetic-snapshot')
    monkeypatch.setattr(module, 'save_failed_request_snapshot', snapshot)
    monkeypatch.setattr(module, 'serialize_client_request_snapshot', lambda request: {})
    attach = Mock()
    monkeypatch.setattr(module, 'attach_request_snapshot', attach)
    request = SimpleNamespace(model_info=SimpleNamespace(name='synthetic-model'), trace_context=None)
    with pytest.raises(LLMTaskTimeoutError) as caught:
        asyncio.run(o._attempt_request_on_model_with_timeout(
            SimpleNamespace(client_type='synthetic'), object(), request, 'synthetic-model'))
    assert state == ['started', 'cancelled']
    snapshot.assert_called_once()
    assert snapshot.call_args.kwargs['operation'] == 'task.hard_timeout'
    attach.assert_called_once_with(caught.value, 'synthetic-snapshot')
