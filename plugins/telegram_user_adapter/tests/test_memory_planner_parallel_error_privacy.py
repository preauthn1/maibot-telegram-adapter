"""Parallel injection failures preserve healthy output without private diagnostics."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.maisaka import reasoning_engine as module

@pytest.mark.parametrize('branch', ['heuristic', 'profile', 'both'])
def test_parallel_injection_error_privacy(monkeypatch, branch):
    engine = object.__new__(module.MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(session_id='synthetic', log_prefix='PRIVATE_SESSION_SENTINEL')
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    heuristic = AsyncMock(return_value='synthetic heuristic')
    profile = AsyncMock(return_value=['synthetic profile'])
    if branch in ('heuristic', 'both'):
        heuristic.side_effect = OSError('PRIVATE_ERROR_SENTINEL')
    if branch in ('profile', 'both'):
        profile.side_effect = ValueError('PRIVATE_ERROR_SENTINEL')
    monkeypatch.setattr(module, 'heuristic_memory_injector', SimpleNamespace(build_injection_message=heuristic))
    monkeypatch.setattr(module, 'build_person_profile_injection_messages', profile)
    result = asyncio.run(engine._build_planner_injected_user_messages(
        profile_message=object(), source_messages=[], deferred_tools_reminder='synthetic reminder'))
    expected = ['synthetic reminder']
    if branch == 'profile':
        expected.append('synthetic heuristic')
    if branch == 'heuristic':
        expected.append('synthetic profile')
    assert result == expected
    heuristic.assert_awaited_once()
    profile.assert_awaited_once()
    logs = str(logger.mock_calls)
    assert 'PRIVATE_SESSION_SENTINEL' not in logs
    assert 'PRIVATE_ERROR_SENTINEL' not in logs
    if branch in ('heuristic', 'both'):
        assert 'OSError' in logs
    if branch in ('profile', 'both'):
        assert 'ValueError' in logs
