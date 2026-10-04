"""恢复说明构造失败时不发布半份历史；再次恢复必须仍可执行。"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.maisaka import runtime as module


def test_reference_failure_does_not_commit_partial_history(monkeypatch):
    runtime=object.__new__(module.MaisakaHeartFlowChatting)
    runtime.session_id='synthetic'
    runtime.log_prefix='synthetic'
    runtime._chat_history=[]
    runtime.message_cache=[]
    row=SimpleNamespace(is_notify=False,is_command=False,message_info=SimpleNamespace(additional_config={}))
    monkeypatch.setattr(module,'find_messages',Mock(return_value=[row]))
    monkeypatch.setattr(module,'logger',Mock())
    monkeypatch.setattr(runtime,'_get_context_restore_limit',lambda:20)
    monkeypatch.setattr(runtime,'_resolve_restored_message_source_kind',lambda m:'user')
    runtime._reasoning_engine=SimpleNamespace(_build_history_message=AsyncMock(return_value='history'))
    reference=Mock(side_effect=ValueError('synthetic reference failure'))
    monkeypatch.setattr(runtime,'_build_context_restore_reference_message',reference)
    with pytest.raises(ValueError):
        asyncio.run(runtime._restore_recent_context_from_db())
    assert runtime._chat_history == []
    assert runtime.message_cache == []
    assert runtime._context_restore_failed is True
    reference.side_effect=None
    reference.return_value=None
    asyncio.run(runtime._restore_recent_context_from_db())
    assert runtime._chat_history == ['history']
    assert runtime.message_cache == [row]
    assert runtime._last_processed_index == 1
    assert reference.call_count == 2


def test_cancel_during_history_build_keeps_state_retryable(monkeypatch):
    runtime=object.__new__(module.MaisakaHeartFlowChatting)
    runtime.session_id='synthetic'
    runtime.log_prefix='synthetic'
    runtime._chat_history=[]
    runtime.message_cache=[]
    rows=[SimpleNamespace(is_notify=False,is_command=False,message_info=SimpleNamespace(additional_config={})) for _ in range(2)]
    monkeypatch.setattr(module,'find_messages',Mock(return_value=rows))
    monkeypatch.setattr(module,'logger',Mock())
    monkeypatch.setattr(runtime,'_get_context_restore_limit',lambda:20)
    monkeypatch.setattr(runtime,'_resolve_restored_message_source_kind',lambda m:'user')
    monkeypatch.setattr(runtime,'_build_context_restore_reference_message',lambda *a,**k:None)

    async def run():
        entered=asyncio.Event()
        async def build(row, **kwargs):
            if row is rows[1]:
                entered.set()
                await asyncio.Event().wait()
            return 'history-first'
        runtime._reasoning_engine=SimpleNamespace(_build_history_message=build)
        task=asyncio.create_task(runtime._restore_recent_context_from_db())
        await asyncio.wait_for(entered.wait(),timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runtime._chat_history == [] and runtime.message_cache == []
        assert runtime._context_restore_failed is True
        runtime._reasoning_engine._build_history_message=AsyncMock(side_effect=['first','second'])
        await runtime._restore_recent_context_from_db()
        assert runtime._chat_history == ['first','second']
        assert runtime.message_cache == rows
        assert runtime._last_processed_index == 2
        assert runtime._context_restore_failed is False
    asyncio.run(run())
