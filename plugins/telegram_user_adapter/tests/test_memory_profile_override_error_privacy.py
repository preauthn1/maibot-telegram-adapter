"""Manual override fallback preserves input without leaking exception details."""
from copy import deepcopy
from unittest.mock import Mock
from src.A_memorix.core.utils import person_profile_service as module


def test_override_read_error_is_private_and_preserves_input(monkeypatch):
    svc = object.__new__(module.PersonProfileService)
    person = 'SYNTHETIC_PRIVATE_PERSON'
    detail = 'SYNTHETIC_PRIVATE_DATABASE_DETAIL'
    svc.metadata_store = Mock()
    svc.metadata_store.get_person_profile_override.side_effect = OSError(detail)
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    original = {'success': True, 'profile_text': 'synthetic automatic profile', 'fact_claim_ids': ['synthetic']}
    before = deepcopy(original)
    result = svc._apply_manual_override(person, original)
    assert original == before
    assert result is not original
    assert result['profile_text'] == before['profile_text']
    assert result['auto_profile_text'] == before['profile_text']
    assert result['has_manual_override'] is False
    assert result['profile_source'] == 'auto_snapshot'
    logged = repr(logger.mock_calls)
    assert detail not in logged
    assert person not in logged
    assert 'OSError' in logged
