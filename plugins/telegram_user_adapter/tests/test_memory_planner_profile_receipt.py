"""Actual planner profile injection rejects non-boolean success receipts."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.memory import person_profile as module

@pytest.mark.parametrize('success', ['false', 'true', 1, False, None, True])
def test_planner_profile_success_boundary(monkeypatch, success):
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(a_memorix=SimpleNamespace(
        integration=SimpleNamespace(enable_person_profile_injection=True, person_profile_injection_max_profiles=3))))
    candidate = SimpleNamespace(person_id='synthetic', person_name='Synthetic', user_id='synthetic-user')
    monkeypatch.setattr(module, 'collect_person_profile_candidates', lambda *a, **kw: [candidate])
    query = AsyncMock(return_value={'success': success, 'person_id': 'synthetic',
                                   'profile_text': 'SYNTHETIC_PROFILE_TEXT'})
    monkeypatch.setattr(module, 'memory_service', SimpleNamespace(profile_admin=query))
    messages = asyncio.run(module.build_person_profile_injection_messages(anchor_message=object()))
    query.assert_awaited_once_with(action='query', person_id='synthetic', limit=module.PROFILE_QUERY_LIMIT)
    if success is True:
        assert len(messages) == 1 and 'SYNTHETIC_PROFILE_TEXT' in messages[0]
    else:
        assert messages == []
