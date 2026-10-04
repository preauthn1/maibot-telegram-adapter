"""Invalid override readbacks must not cross person boundaries."""
from unittest.mock import Mock
import pytest
from src.A_memorix.core.utils.person_profile_service import PersonProfileService

@pytest.mark.parametrize('record', [
    {'person_id': 'other', 'override_text': 'SYNTHETIC_OTHER'},
    {'override_text': 'SYNTHETIC_MISSING_OWNER'},
    {'person_id': 'synthetic', 'override_text': {'text': 'bad'}},
    {'person_id': 'synthetic', 'override_text': ['bad']},
])
def test_invalid_override_readback_keeps_auto(record):
    svc = object.__new__(PersonProfileService)
    svc.metadata_store = Mock()
    svc.metadata_store.get_person_profile_override.return_value = record
    original = {'success': True, 'profile_text': 'synthetic automatic'}
    result = svc._apply_manual_override('synthetic', original)
    assert result['profile_text'] == 'synthetic automatic'
    assert result['has_manual_override'] is False
    assert original == {'success': True, 'profile_text': 'synthetic automatic'}


def test_matching_override_readback_is_applied():
    svc = object.__new__(PersonProfileService)
    svc.metadata_store = Mock()
    svc.metadata_store.get_person_profile_override.return_value = {
        'person_id': 'synthetic', 'override_text': 'synthetic manual'}
    result = svc._apply_manual_override('synthetic', {'profile_text': 'synthetic automatic'})
    assert result['has_manual_override'] is True
    assert result['profile_text'] == 'synthetic manual'
