"""Profile admin diagnostics must not expose raw host exceptions."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.services import memory_service as module

@pytest.mark.parametrize('error_type', [OSError, ValueError])
def test_profile_admin_private_error(monkeypatch, error_type):
    invoke = AsyncMock(side_effect=error_type('PRIVATE_DIAGNOSTIC_SENTINEL'))
    monkeypatch.setattr(module, 'a_memorix_host_service', SimpleNamespace(invoke=invoke))
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    result = asyncio.run(module.MemoryService().profile_admin(action='query', person_id='synthetic'))
    assert result == {'success': False, 'error': 'profile_admin_failed:' + error_type.__name__}
    assert 'PRIVATE_DIAGNOSTIC_SENTINEL' not in str(logger.mock_calls)
    assert error_type.__name__ in str(logger.mock_calls)
    invoke.assert_awaited_once_with('memory_profile_admin', {'action': 'query', 'person_id': 'synthetic'})


def test_profile_admin_cancel_and_success(monkeypatch):
    failure = asyncio.CancelledError('synthetic cancellation')
    invoke = AsyncMock(side_effect=failure)
    monkeypatch.setattr(module, 'a_memorix_host_service', SimpleNamespace(invoke=invoke))
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    with pytest.raises(asyncio.CancelledError) as caught:
        asyncio.run(module.MemoryService().profile_admin(action='query', person_id='synthetic'))
    assert caught.value is failure
    assert not logger.warning.called
    payload = {'success': True, 'person_id': 'synthetic', 'profile_text': 'synthetic text'}
    invoke.side_effect = None
    invoke.return_value = SimpleNamespace(payload={'result': payload})
    assert asyncio.run(module.MemoryService().profile_admin(action='query', person_id='synthetic')) == payload
