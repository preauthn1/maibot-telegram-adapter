"""Cancelling planner injection must clean up both gather branches."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.maisaka import reasoning_engine as module


def test_parallel_injection_cancellation_cleans_both_branches(monkeypatch):
    engine = object.__new__(module.MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(session_id='synthetic-session', log_prefix='synthetic')
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)

    async def scenario():
        entered = [asyncio.Event(), asyncio.Event()]
        cleaned = [asyncio.Event(), asyncio.Event()]
        async def wait_branch(index):
            try:
                entered[index].set()
                await asyncio.Event().wait()
            finally:
                cleaned[index].set()
        async def heuristic(**kwargs):
            assert kwargs == {'session_id': 'synthetic-session'}
            return await wait_branch(0)
        anchor = object()
        sources = [anchor]
        async def profile(**kwargs):
            assert kwargs['anchor_message'] is anchor
            assert kwargs['pending_messages'] is sources
            return await wait_branch(1)
        monkeypatch.setattr(module, 'heuristic_memory_injector', SimpleNamespace(build_injection_message=heuristic))
        monkeypatch.setattr(module, 'build_person_profile_injection_messages', profile)
        task = asyncio.create_task(engine._build_planner_injected_user_messages(
            profile_message=anchor, source_messages=sources, deferred_tools_reminder='synthetic reminder'))
        try:
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), 2)
            assert task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
            assert task.cancelled()
            assert all(event.is_set() for event in cleaned)
            assert not logger.debug.called
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())
