"""Malformed injection outputs must not corrupt planner message lists."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from src.maisaka import reasoning_engine as module

@pytest.mark.parametrize('heuristic, profiles, expected', [
    ('valid heuristic', 'bad string', ['reminder', 'valid heuristic']),
    ('valid heuristic', None, ['reminder', 'valid heuristic']),
    ('valid heuristic', {'bad': 'object'}, ['reminder', 'valid heuristic']),
    ({'bad': 'object'}, ['valid profile'], ['reminder', 'valid profile']),
    (42, ['valid profile'], ['reminder', 'valid profile']),
    ('  ', ['valid profile'], ['reminder', 'valid profile']),
    ('valid heuristic', ['valid profile', None, 42, {}, '', '  '], ['reminder', 'valid heuristic', 'valid profile']),
    ('  valid heuristic\n', [' valid profile\n'], ['reminder', '  valid heuristic\n', ' valid profile\n']),
])
def test_parallel_result_types(monkeypatch, heuristic, profiles, expected):
    engine = object.__new__(module.MaisakaReasoningEngine)
    engine._runtime = SimpleNamespace(session_id='synthetic', log_prefix='synthetic')
    monkeypatch.setattr(module, 'heuristic_memory_injector', SimpleNamespace(
        build_injection_message=AsyncMock(return_value=heuristic)))
    monkeypatch.setattr(module, 'build_person_profile_injection_messages', AsyncMock(return_value=profiles))
    result = asyncio.run(engine._build_planner_injected_user_messages(
        profile_message=object(), source_messages=[], deferred_tools_reminder='reminder'))
    assert result == expected
