"""Live task cancellation remains cancellation despite ordinary cleanup failures."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.maisaka import reasoning_engine as module

@pytest.mark.parametrize('cleanup', ['unbind', 'reset', 'both'])
def test_live_cancel_cleanup(monkeypatch, cleanup):
    engine = object.__new__(module.MaisakaReasoningEngine)
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    async def scenario():
        entered = asyncio.Event()
        cleaned = asyncio.Event()
        flags = []
        async def request(*args, **kwargs):
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        def setter(flag):
            flags.append(flag)
            if flag is None and cleanup in ('reset', 'both'):
                raise ValueError('PRIVATE_CLEANUP_SENTINEL')
        unbind = Mock(side_effect=OSError('PRIVATE_CLEANUP_SENTINEL') if cleanup in ('unbind', 'both') else None)
        engine._runtime = SimpleNamespace(
            _bind_planner_interrupt_flag=Mock(), _unbind_planner_interrupt_flag=unbind,
            _chat_loop_service=SimpleNamespace(set_interrupt_flag=setter, chat_loop_step=request),
            _chat_history=[], _max_context_size=12)
        engine._active_logical_turn_id = 'synthetic'
        task = asyncio.create_task(engine._run_interruptible_planner())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert task.cancelled()
            assert cleaned.is_set()
            assert len(flags) == 2 and flags[-1] is None
            unbind.assert_called_once_with(flags[0], interrupted=False)
            assert 'PRIVATE_CLEANUP_SENTINEL' not in str(logger.mock_calls)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
