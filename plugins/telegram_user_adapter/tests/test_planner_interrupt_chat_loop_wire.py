"""Real interrupt controller lifecycle through the actual request wrapper."""
import asyncio
from types import SimpleNamespace
import pytest
from src.maisaka.runtime import PlannerInterruptController
from src.maisaka import reasoning_engine as module
from src.maisaka.chat_loop_service import MaisakaChatLoopService

@pytest.mark.parametrize('outcome', ['success', 'error', 'abort'])
def test_actual_chat_loop_flag_lifecycle(outcome, monkeypatch):
    controller = PlannerInterruptController()
    engine = object.__new__(module.MaisakaReasoningEngine)
    loop = object.__new__(MaisakaChatLoopService)
    loop._interrupt_flag = None
    response = object()
    failure = module.ReqAbortException('synthetic abort') if outcome == 'abort' else OSError('synthetic failure')
    async def request(*args, **kwargs):
        assert controller.request(max_consecutive_count=3) == 'request'
        assert isinstance(loop._interrupt_flag, asyncio.Event)
        assert controller._flag is loop._interrupt_flag
        assert loop._interrupt_flag.is_set()
        assert controller.request(max_consecutive_count=3) == 'duplicate'
        if outcome != 'success':
            raise failure
        return response
    monkeypatch.setattr(loop, 'chat_loop_step', request)
    engine._runtime = SimpleNamespace(
        _bind_planner_interrupt_flag=controller.bind,
        _unbind_planner_interrupt_flag=controller.unbind,
        _chat_loop_service=loop,
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic'
    if outcome == 'success':
        assert asyncio.run(engine._run_interruptible_planner()) is response
    else:
        with pytest.raises(type(failure)) as caught:
            asyncio.run(engine._run_interruptible_planner())
        assert caught.value is failure
    assert loop._interrupt_flag is None
    assert controller.request(max_consecutive_count=3) == 'idle'
    assert controller.consecutive_count == (1 if outcome == 'abort' else 0)
    # The next actual binding can receive a new interrupt, not a stale duplicate.
    following = asyncio.Event()
    controller.bind(following)
    assert controller.request(max_consecutive_count=3) == 'request'
    assert following.is_set()
    controller.unbind(following, interrupted=False)
    assert controller.consecutive_count == 0
