"""后台通知异常被消费，不进入事件循环的未处理异常通道。"""
import asyncio
import gc
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.services.llm_service import LLMServiceClient
from src.llm_models import utils_model as module


@pytest.mark.parametrize('outcome', ['failure', 'success', 'cancel'])
@pytest.mark.parametrize('event_kind', ['error', 'retry'])
def test_background_notification_failure_is_consumed(monkeypatch, outcome, event_kind):
    received = []
    event_args = dict(model_name='synthetic', message='synthetic') if event_kind == 'error' else dict(
        model_name='synthetic', attempt=2, max_attempts=3, reason='synthetic retry', retry_interval=0)
    service = LLMServiceClient('replyer', request_type='synthetic', session_id='synthetic')
    warning = Mock()
    monkeypatch.setattr(module.logger, 'warning', warning)
    unhandled = []
    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda loop, context: unhandled.append(context))
        async def fail(**kwargs):
            received.append(kwargs)
            if outcome == 'failure':
                raise OSError('SYNTHETIC_EVENT_PRIVATE_MARKER')
            if outcome == 'cancel':
                raise asyncio.CancelledError()
        monkeypatch.setitem(sys.modules, 'src.maisaka.monitor.events', SimpleNamespace(emit_llm_error=fail, emit_llm_retry=fail))
        getattr(service._orchestrator, '_schedule_llm_' + event_kind + '_event')(**event_args)
        for _ in range(4):
            await asyncio.sleep(0)
        gc.collect()
        await asyncio.sleep(0)
    asyncio.run(scenario())
    assert unhandled == []
    assert received == [dict(session_id='synthetic', task_name=service._orchestrator.task_name,
                             request_type='synthetic', **event_args)]
    assert warning.call_count == (1 if outcome == 'failure' else 0)
    logged = str(warning.call_args_list)
    if outcome == 'failure':
        assert 'OSError' in logged
    assert 'SYNTHETIC_EVENT_PRIVATE_MARKER' not in logged
