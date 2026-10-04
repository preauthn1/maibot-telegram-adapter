"""后台循环真实逻辑，批次替身；零等待调度，不调用模型。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.A_memorix.core.runtime.services import background_task_service as module

@pytest.mark.parametrize('cancel',[False,True])
def test_batch_error_does_not_end_loop(monkeypatch,cancel):
    logs=Mock();monkeypatch.setattr(module,'logger',logs)
    svc=SimpleNamespace(_background_stopping=False,
        _paragraph_vector_backfill_interval_seconds=lambda:0,
        _paragraph_vector_backfill_enabled=lambda:True,_is_embedding_degraded=lambda:False,
        _paragraph_vector_backfill_batch_size=lambda:2,_paragraph_vector_backfill_max_retry=lambda:3)
    calls=[]
    error=asyncio.CancelledError() if cancel else OSError('SYNTHETIC_PRIVATE_BODY')
    async def batch(**kw):
        calls.append(kw)
        if len(calls)==1:raise error
        svc._background_stopping=True
    svc._run_paragraph_backfill_once=AsyncMock(side_effect=batch)
    async def run():
        await asyncio.wait_for(module.MemoryBackgroundTaskService._paragraph_vector_backfill_loop(svc),timeout=2)
    if cancel:
        with pytest.raises(asyncio.CancelledError):asyncio.run(run())
        assert len(calls)==1
    else:
        asyncio.run(run())
        assert len(calls)==2
        assert calls[1]==dict(limit=2,max_retry=3,trigger='loop')
        assert 'SYNTHETIC_PRIVATE_BODY' not in str(logs.mock_calls)
