"""Real task cancellation propagates through the planner profile entry point."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.maisaka.memory import person_profile as module


def test_planner_profile_task_cancel(monkeypatch):
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(a_memorix=SimpleNamespace(
        integration=SimpleNamespace(enable_person_profile_injection=True, person_profile_injection_max_profiles=3))))
    candidates = [SimpleNamespace(person_id=pid, person_name='Synthetic', user_id='synthetic-user')
                  for pid in ['synthetic-first', 'synthetic-waiting', 'synthetic-last']]
    monkeypatch.setattr(module, 'collect_person_profile_candidates', lambda *a, **kw: candidates)
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)

    async def scenario():
        entered = asyncio.Event()
        released = asyncio.Event()
        calls = []

        async def query(**kwargs):
            pid = kwargs['person_id']
            calls.append(pid)
            if pid == 'synthetic-first':
                return {'success': True, 'person_id': pid, 'profile_text': 'synthetic first profile'}
            try:
                entered.set()
                await asyncio.Event().wait()
            finally:
                released.set()

        monkeypatch.setattr(module, 'memory_service', SimpleNamespace(profile_admin=query))
        task = asyncio.create_task(module.build_person_profile_injection_messages(anchor_message=object()))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            assert task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=2)
            assert task.cancelled()
            assert released.is_set()
            assert calls == ['synthetic-first', 'synthetic-waiting']
            assert not logger.debug.called
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    asyncio.run(scenario())
