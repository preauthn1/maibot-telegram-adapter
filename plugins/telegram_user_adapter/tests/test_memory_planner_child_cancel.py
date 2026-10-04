"""A cancelled injection child must not leave its sibling running."""
import asyncio
from types import SimpleNamespace
import pytest
from src.maisaka import reasoning_engine as module

@pytest.mark.parametrize('cancel_branch', ['profile', 'heuristic'])
def test_child_cancel_cleans_sibling(monkeypatch, cancel_branch):
    engine = object.__new__(module.MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(session_id='synthetic', log_prefix='synthetic')
    async def scenario():
        entered = asyncio.Event()
        cleaned = asyncio.Event()
        children = []
        async def branch(name):
            children.append(asyncio.current_task())
            if name == cancel_branch:
                await entered.wait()
                raise asyncio.CancelledError('synthetic child cancellation')
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleaned.set()
        async def heuristic(**kwargs):
            return await branch('heuristic')
        async def profile(**kwargs):
            return await branch('profile')
        monkeypatch.setattr(module, 'heuristic_memory_injector', SimpleNamespace(build_injection_message=heuristic))
        monkeypatch.setattr(module, 'build_person_profile_injection_messages', profile)
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(engine._build_planner_injected_user_messages(
                    profile_message=object(), source_messages=[], deferred_tools_reminder='synthetic'), 2)
            assert cleaned.is_set()
            assert all(task.done() for task in children)
        finally:
            for task in children:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*children, return_exceptions=True)
    asyncio.run(scenario())
