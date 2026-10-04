"""Planner text validation uses the actual injection entry point."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka.memory import person_profile as module

@pytest.mark.parametrize('fields, expected', [
    ({'profile_text': value}, '') for value in [{'text': 'bad'}, ['bad'], 42, True, b'bad']
] + [
    ({'summary': value}, '') for value in [{'text': 'bad'}, ['bad'], 42, True, b'bad']
] + [
    ({'profile_text': 'synthetic primary', 'summary': 'synthetic fallback'}, 'synthetic primary'),
    ({'summary': 'synthetic fallback'}, 'synthetic fallback'),
    ({'profile_text': '', 'summary': 'synthetic fallback'}, 'synthetic fallback'),
    ({'profile_text': None, 'summary': 'synthetic fallback'}, 'synthetic fallback'),
    ({'profile_text': False, 'summary': 'synthetic fallback'}, ''),
    ({'profile_text': {}, 'summary': 'synthetic fallback'}, ''),
])
def test_planner_profile_text(monkeypatch, fields, expected):
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(a_memorix=SimpleNamespace(
        integration=SimpleNamespace(enable_person_profile_injection=True, person_profile_injection_max_profiles=3))))
    candidate = SimpleNamespace(person_id='synthetic', person_name='Synthetic', user_id='synthetic-user')
    monkeypatch.setattr(module, 'collect_person_profile_candidates', lambda *a, **kw: [candidate])
    query = AsyncMock(return_value=dict(success=True, person_id='synthetic', **fields))
    monkeypatch.setattr(module, 'memory_service', SimpleNamespace(profile_admin=query))
    messages = asyncio.run(module.build_person_profile_injection_messages(anchor_message=object()))
    query.assert_awaited_once()
    if expected:
        assert len(messages) == 1 and expected in messages[0]
        if expected == 'synthetic primary':
            assert 'synthetic fallback' not in messages[0]
    else:
        assert messages == []
