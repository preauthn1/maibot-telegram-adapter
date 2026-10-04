"""Actual JSON repair/parser must not stringify structured values into facts."""
import json
import pytest
from src.A_memorix.core.utils.person_profile_service import PersonProfileService as Service

@pytest.mark.parametrize('key', ['identity_settings', 'relationship_settings', 'stable_facts',
    'interaction_preferences', 'recent_interactions', 'uncertain_notes'])
def test_profile_parser_only_accepts_text_items(key):
    raw = json.dumps({key: [' synthetic fact ', 42, True, {'text': 'not a fact'},
                            ['nested'], None, False, 0, '', '  ']})
    parsed = Service._parse_profile_classification_response(raw)
    assert parsed[key] == ['synthetic fact']
    assert all(values == [] for name, values in parsed.items() if name != key)


def test_profile_parser_keeps_other_valid_sections():
    parsed = Service._parse_profile_classification_response(json.dumps({
        'stable_facts': {'wrong': 'shape'}, 'uncertain_notes': ['valid note'],
        'unknown': ['ignored']}))
    assert parsed['stable_facts'] == []
    assert parsed['uncertain_notes'] == ['valid note']
    assert 'unknown' not in parsed
