"""Reject malformed profile receipts at the reply reference boundary."""
import pytest
from src.A_memorix.core.utils.person_profile_service import PersonProfileService as Service

@pytest.mark.parametrize('success', ['false', 'true', 1, None, False])
def test_invalid_success_not_injected(success):
    assert Service.format_persona_profile_block({'success': success, 'profile_text': 'synthetic manual'}) == ''

@pytest.mark.parametrize('text', [{'text': 'synthetic'}, ['synthetic'], 42, True, b'synthetic'])
def test_nontext_profile_not_injected(text):
    assert Service.format_persona_profile_block({'success': True, 'profile_text': text}) == ''


def test_valid_profile_injected():
    block = Service.format_persona_profile_block({'success': True, 'profile_text': 'synthetic manual'})
    assert 'synthetic manual' in block
    assert '人物画像-内部参考' in block
