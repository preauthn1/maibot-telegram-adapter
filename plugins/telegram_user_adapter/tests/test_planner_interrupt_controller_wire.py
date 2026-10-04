"""Real interrupt controller lifecycle through the actual request wrapper."""
import asyncio
from types import SimpleNamespace
import pytest
from src.maisaka.runtime import PlannerInterruptController
from src.maisaka import reasoning_engine as module

@pytest.mark.parametrize('outcome', ['success', 'error', 'abort'])
def test_actual_controller_request_lifecycle(outcome):
    controller = PlannerInterruptController()
    engine = object.__new__(module.MaisakaReasoningEngine)
    flags = []
    response = object()
    failure = module.ReqAbortException('synthetic abort') if outcome == 'abort' else OSError('synthetic failure')
    async def request(*args, **kwargs):
        assert controller.request(max_consecutive_count=3) == 'request'
        assert flags[-1].is_set()
        assert controller.request(max_consecutive_count=3) == 'duplicate'
        if outcome != 'success':
            raise failure
        return response
    engine._runtime = SimpleNamespace(
        _bind_planner_interrupt_flag=controller.bind,
        _unbind_planner_interrupt_flag=controller.unbind,
        _chat_loop_service=SimpleNamespace(set_interrupt_flag=flags.append, chat_loop_step=request),
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic'
    if outcome == 'success':
        assert asyncio.run(engine._run_interruptible_planner()) is response
    else:
        with pytest.raises(type(failure)) as caught:
            asyncio.run(engine._run_interruptible_planner())
        assert caught.value is failure
    assert flags[-1] is None
    assert controller.request(max_consecutive_count=3) == 'idle'
    assert controller.consecutive_count == (1 if outcome == 'abort' else 0)
    # The next actual binding can receive a new interrupt, not a stale duplicate.
    following = asyncio.Event()
    controller.bind(following)
    assert controller.request(max_consecutive_count=3) == 'request'
    assert following.is_set()
    controller.unbind(following, interrupted=False)
    assert controller.consecutive_count == 0
