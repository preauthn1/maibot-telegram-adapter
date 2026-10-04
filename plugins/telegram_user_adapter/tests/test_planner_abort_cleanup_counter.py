"""Abort identity and real interrupt count survive post-cleanup errors."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.maisaka.runtime import PlannerInterruptController
from src.maisaka import reasoning_engine as module

@pytest.mark.parametrize('cleanup', ['unbind', 'reset', 'both'])
def test_abort_cleanup_keeps_counter(monkeypatch, cleanup):
    controller = PlannerInterruptController()
    engine = object.__new__(module.MaisakaReasoningEngine)
    flags = []
    modes = []
    original = module.ReqAbortException('PRIVATE_ABORT')
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    def unbind(flag, *, interrupted):
        modes.append(interrupted)
        controller.unbind(flag, interrupted=interrupted)
        if cleanup in ('unbind', 'both'):
            raise OSError('PRIVATE_CLEANUP')
    def setter(flag):
        flags.append(flag)
        if flag is None and cleanup in ('reset', 'both'):
            raise ValueError('PRIVATE_CLEANUP')
    async def request(*args, **kwargs):
        assert controller.request(max_consecutive_count=1) == 'request'
        raise original
    engine._runtime = SimpleNamespace(_bind_planner_interrupt_flag=controller.bind,
        _unbind_planner_interrupt_flag=unbind,
        _chat_loop_service=SimpleNamespace(set_interrupt_flag=setter, chat_loop_step=request),
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic'
    with pytest.raises(module.ReqAbortException) as caught:
        asyncio.run(engine._run_interruptible_planner())
    assert caught.value is original
    assert modes == [True]
    assert len(flags) == 2 and flags[-1] is None
    assert controller.consecutive_count == 1
    assert controller.request(max_consecutive_count=1) == 'idle'
    following = asyncio.Event()
    controller.bind(following)
    assert controller.request(max_consecutive_count=1) == 'limit'
    assert not following.is_set()
    controller.unbind(following, interrupted=False)
    assert controller.consecutive_count == 0
    assert 'PRIVATE_' not in str(logger.mock_calls)
