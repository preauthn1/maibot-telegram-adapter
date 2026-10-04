"""Older wrapper cleanup must preserve a newer request's loop flag."""
import asyncio
from types import SimpleNamespace
import pytest
from src.maisaka.runtime import PlannerInterruptController
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.maisaka.reasoning_engine import MaisakaReasoningEngine

def test_cancel_old_request_preserves_new_binding(monkeypatch):
    controller = PlannerInterruptController()
    loop = object.__new__(MaisakaChatLoopService)
    loop._interrupt_flag = None
    engine = object.__new__(MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(_bind_planner_interrupt_flag=controller.bind,
        _unbind_planner_interrupt_flag=controller.unbind, _chat_loop_service=loop,
        _chat_history=[], _max_context_size=12)
    engine._active_logical_turn_id = 'synthetic'
    async def scenario():
        entered = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        flags, tasks = [], []
        async def request(*args, **kwargs):
            index = len(flags)
            flags.append(loop._interrupt_flag)
            entered[index].set()
            await release[index].wait()
            return index
        monkeypatch.setattr(loop, 'chat_loop_step', request)
        try:
            for index in range(2):
                tasks.append(asyncio.create_task(engine._run_interruptible_planner()))
                await asyncio.wait_for(entered[index].wait(), 2)
            assert flags[0] is not flags[1]
            assert controller.request(max_consecutive_count=3) == 'request'
            assert controller.consecutive_count == 1
            assert tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(tasks[0], 2)
            assert tasks[0].cancelled()
            assert not tasks[1].done()
            assert loop._interrupt_flag is flags[1]
            assert controller._flag is flags[1]
            assert controller.consecutive_count == 1
            assert controller.request(max_consecutive_count=3) == 'duplicate'
            assert flags[1].is_set()
            release[1].set()
            assert await asyncio.wait_for(tasks[1], 2) == 1
            assert controller.consecutive_count == 0
            assert loop._interrupt_flag is None
            assert controller.request(max_consecutive_count=3) == 'idle'
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(scenario())
