"""Explicitly mismatched profile ownership must not enter planner context."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.memory import person_profile as module

@pytest.mark.parametrize('owner', ['synthetic-other', '', None, 42, False, ['synthetic-target']])
def test_mismatched_owner_is_skipped(monkeypatch, owner):
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(a_memorix=SimpleNamespace(
        integration=SimpleNamespace(enable_person_profile_injection=True, person_profile_injection_max_profiles=3))))
    candidates = [SimpleNamespace(person_id=pid, person_name='Synthetic', user_id='synthetic-user')
                  for pid in ['synthetic-target', 'synthetic-good']]
    monkeypatch.setattr(module, 'collect_person_profile_candidates', lambda *a, **kw: candidates)
    query = AsyncMock(side_effect=[
        {'success': True, 'person_id': owner, 'profile_text': 'WRONG_PROFILE_SENTINEL'},
        {'success': True, 'person_id': 'synthetic-good', 'profile_text': 'GOOD_PROFILE_SENTINEL'}])
    monkeypatch.setattr(module, 'memory_service', SimpleNamespace(profile_admin=query))
    messages = asyncio.run(module.build_person_profile_injection_messages(anchor_message=object()))
    assert query.await_count == 2
    assert len(messages) == 1
    assert 'WRONG_PROFILE_SENTINEL' not in messages[0]
    assert 'GOOD_PROFILE_SENTINEL' in messages[0]
