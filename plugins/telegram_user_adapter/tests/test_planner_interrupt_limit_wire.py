"""Consecutive interruption limits survive real request-wrapper cleanup."""
import asyncio
from types import SimpleNamespace
import pytest
from src.maisaka.runtime import PlannerInterruptController
from src.maisaka import reasoning_engine as module

@pytest.mark.parametrize('limit', [1, 2, 3])
def test_request_wrapper_interrupt_limit_and_recovery(limit):
    controller = PlannerInterruptController()
    engine = object.__new__(module.MaisakaReasoningEngine)
    flags = []
    states = []
    async def request(*args, **kwargs):
        status = controller.request(max_consecutive_count=limit)
        states.append(status)
        if status == 'request':
            assert flags[-1].is_set()
            raise module.ReqAbortException('synthetic interruption')
        assert status == 'limit'
        assert not flags[-1].is_set()
        return 'synthetic completed response'
    engine._runtime = SimpleNamespace(
        _bind_planner_interrupt_flag=controller.bind,
        _unbind_planner_interrupt_flag=controller.unbind,
        _chat_loop_service=SimpleNamespace(set_interrupt_flag=flags.append, chat_loop_step=request),
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic'
    async def scenario():
        for index in range(limit):
            with pytest.raises(module.ReqAbortException):
                await engine._run_interruptible_planner()
            assert controller.consecutive_count == index + 1
            assert flags[-1] is None
            assert controller.request(max_consecutive_count=limit) == 'idle'
        assert await engine._run_interruptible_planner() == 'synthetic completed response'
        assert controller.consecutive_count == 0
        assert states == ['request'] * limit + ['limit']
        with pytest.raises(module.ReqAbortException):
            await engine._run_interruptible_planner()
        assert states[-1] == 'request'
        assert controller.consecutive_count == 1
        assert flags[-1] is None
        assert controller.request(max_consecutive_count=limit) == 'idle'
    asyncio.run(scenario())
