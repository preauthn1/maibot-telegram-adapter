"""调用方取消挂起请求时，应释放占用且不切换模型。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.services.llm_service import LLMServiceClient


@pytest.mark.parametrize('real_timeout_wrapper', [False, True])
def test_external_cancel_releases_model_usage(monkeypatch, real_timeout_wrapper):

    service = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    o = service._orchestrator
    def select(**kwargs):
        o.model_usage['synthetic'] = (12, 3, 1)
        return SimpleNamespace(name='synthetic'), object(), object()
    selection = Mock(side_effect=select)
    monkeypatch.setattr(o, '_select_model', selection)
    monkeypatch.setattr(o, '_build_client_request', lambda **kw: object())
    event = Mock()
    monkeypatch.setattr(o, '_schedule_llm_error_event', event)
    from src.llm_models import utils_model as module
    snapshot = Mock()
    monkeypatch.setattr(module, 'save_failed_request_snapshot', snapshot)
    if real_timeout_wrapper:
        monkeypatch.setattr(o, '_refresh_task_config', lambda: o.model_for_task)
        o.model_for_task = SimpleNamespace(model_list=['synthetic'], hard_timeout=60)
    cleaned = []
    async def scenario():
        started = asyncio.Event()
        async def pending(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.append(True)
        method = '_attempt_request_on_model' if real_timeout_wrapper else '_attempt_request_on_model_with_timeout'
        monkeypatch.setattr(o, method, pending)
        task = asyncio.create_task(service.generate_response_with_context(lambda client: []))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert cleaned == [True]
    selection.assert_called_once()
    event.assert_not_called()
    snapshot.assert_not_called()
    assert o.model_usage['synthetic'] == (12, 3, 0)
