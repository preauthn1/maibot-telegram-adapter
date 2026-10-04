"""Parent cancellation propagation waits for asynchronous sibling cleanup."""
import asyncio
from types import SimpleNamespace
import pytest
from src.maisaka import reasoning_engine as module

@pytest.mark.parametrize('cancel_branch', ['profile', 'heuristic'])
def test_parent_waits_for_async_cleanup(monkeypatch, cancel_branch):
    engine = object.__new__(module.MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(session_id='synthetic', log_prefix='synthetic')
    async def scenario():
        entered = asyncio.Event()
        cleaning = asyncio.Event()
        release = asyncio.Event()
        cleaned = asyncio.Event()
        children = []
        original = asyncio.CancelledError('synthetic cancellation')
        async def branch(name):
            children.append(asyncio.current_task())
            if name == cancel_branch:
                await entered.wait()
                raise original
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                cleaning.set()
                await release.wait()
                cleaned.set()
        async def heuristic(**kwargs):
            return await branch('heuristic')
        async def profile(**kwargs):
            return await branch('profile')
        monkeypatch.setattr(module, 'heuristic_memory_injector', SimpleNamespace(build_injection_message=heuristic))
        monkeypatch.setattr(module, 'build_person_profile_injection_messages', profile)
        parent = asyncio.create_task(engine._build_planner_injected_user_messages(
            profile_message=object(), source_messages=[], deferred_tools_reminder='synthetic'))
        try:
            await asyncio.wait_for(cleaning.wait(), 2)
            # Let already scheduled continuations run without releasing cleanup.
            await asyncio.sleep(0)
            assert not parent.done()
            assert not cleaned.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError) as caught:
                await asyncio.wait_for(parent, 2)
            assert caught.value is original
            assert cleaned.is_set()
            assert all(task.done() for task in children)
        finally:
            release.set()
            for task in [parent, *children]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(parent, *children, return_exceptions=True)
    asyncio.run(scenario())
