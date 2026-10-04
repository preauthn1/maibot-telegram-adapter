"""Older wrapper cleanup must preserve a newer request's loop flag."""
import asyncio
from types import SimpleNamespace
import pytest
from src.maisaka.runtime import PlannerInterruptController
from src.maisaka.chat_loop_service import MaisakaChatLoopService
from src.maisaka.reasoning_engine import MaisakaReasoningEngine

@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
def test_overlap_cleanup_ownership(monkeypatch, order):
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
            first, second = order
            release[first].set()
            assert await asyncio.wait_for(tasks[first], 2) == first
            if first == 0:
                assert loop._interrupt_flag is flags[1]
                assert controller.request(max_consecutive_count=3) == 'request'
                assert flags[1].is_set()
            else:
                assert loop._interrupt_flag is None
            release[second].set()
            assert await asyncio.wait_for(tasks[second], 2) == second
            assert loop._interrupt_flag is None
            assert controller.request(max_consecutive_count=3) == 'idle'
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(scenario())
