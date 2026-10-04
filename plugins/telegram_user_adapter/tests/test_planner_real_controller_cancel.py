"""Actual controller and loop flag storage survive live task cancellation."""
import asyncio
from types import SimpleNamespace
import pytest
from src.maisaka.runtime import PlannerInterruptController
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.maisaka import reasoning_engine as module


def test_real_controller_live_cancel_and_next_request(monkeypatch):
    controller = PlannerInterruptController()
    engine = object.__new__(module.MaisakaReasoningEngine)
    loop = object.__new__(MaisakaChatLoopService)
    loop._interrupt_flag = None
    engine._runtime = SimpleNamespace(
        _bind_planner_interrupt_flag=controller.bind,
        _unbind_planner_interrupt_flag=controller.unbind,
        _chat_loop_service=loop, _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic'

    async def scenario():
        entered = asyncio.Event()
        cleaned = asyncio.Event()
        seen = []
        async def waiting(*args, **kwargs):
            seen.append(loop._interrupt_flag)
            assert controller._flag is loop._interrupt_flag
            assert controller.request(max_consecutive_count=3) == 'request'
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        monkeypatch.setattr(loop, 'chat_loop_step', waiting)
        task = asyncio.create_task(engine._run_interruptible_planner())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert task.cancelled() and cleaned.is_set()
            assert loop._interrupt_flag is None
            assert controller.request(max_consecutive_count=3) == 'idle'
            assert controller.consecutive_count == 0
            async def following(*args, **kwargs):
                assert loop._interrupt_flag is not seen[0]
                assert controller._flag is loop._interrupt_flag
                assert not loop._interrupt_flag.is_set()
                assert controller.request(max_consecutive_count=3) == 'request'
                return 'synthetic response'
            monkeypatch.setattr(loop, 'chat_loop_step', following)
            assert await engine._run_interruptible_planner() == 'synthetic response'
            assert loop._interrupt_flag is None
            assert controller.consecutive_count == 0
            assert controller.request(max_consecutive_count=3) == 'idle'
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
