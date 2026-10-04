"""Planner failures must not log raw identities or provider diagnostics."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.maisaka.memory import person_profile as module

@pytest.mark.parametrize('failure', ['exception', 'receipt', 'empty'])
def test_planner_error_privacy_and_continuation(monkeypatch, failure):
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(a_memorix=SimpleNamespace(
        integration=SimpleNamespace(enable_person_profile_injection=True, person_profile_injection_max_profiles=3))))
    candidates = [SimpleNamespace(person_id=pid, person_name='Synthetic', user_id='synthetic-user')
                  for pid in ['PRIVATE_PERSON_SENTINEL', 'synthetic-good']]
    monkeypatch.setattr(module, 'collect_person_profile_candidates', lambda *a, **kw: candidates)
    bad = {'success': False, 'error': 'PRIVATE_ERROR_SENTINEL'}
    if failure == 'exception':
        bad = OSError('PRIVATE_ERROR_SENTINEL')
    elif failure == 'empty':
        bad = {'success': True, 'profile_text': ''}
    query = AsyncMock(side_effect=[bad, {'success': True, 'person_id': 'synthetic-good',
                                        'profile_text': 'SYNTHETIC_GOOD_PROFILE'}])
    monkeypatch.setattr(module, 'memory_service', SimpleNamespace(profile_admin=query))
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    messages = asyncio.run(module.build_person_profile_injection_messages(anchor_message=object()))
    assert query.await_count == 2
    assert len(messages) == 1 and 'SYNTHETIC_GOOD_PROFILE' in messages[0]
    logs = str(logger.mock_calls)
    assert logger.debug.called
    assert 'PRIVATE_PERSON_SENTINEL' not in logs
    assert 'PRIVATE_ERROR_SENTINEL' not in logs
    if failure == 'exception':
        assert 'OSError' in logs
