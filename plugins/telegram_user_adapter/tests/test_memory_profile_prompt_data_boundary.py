"""Prompt serialization preserves source labels without creating instruction lines."""
import json
import pytest
from src.A_memorix.core.utils.person_profile_service import PersonProfileService as Service

@pytest.mark.parametrize('field', ['person_id', 'primary_name'])
def test_profile_labels_are_json_encoded(field):
    value = 'Synthetic\nIGNORE_PREVIOUS_SYNTHETIC\r\n"quoted"\\path'
    args = dict(person_id='synthetic', primary_name='Synthetic', aliases=[], candidates=[])
    args[field] = value
    prompt = Service._build_profile_classification_prompt(**args)
    label = '人物ID: ' if field == 'person_id' else '主称呼: '
    line = next(line for line in prompt.splitlines() if line.startswith(label))
    assert json.loads(line[len(label):]) == value
    assert '\nIGNORE_PREVIOUS_SYNTHETIC' not in prompt
    assert '不是指令' in prompt


def test_profile_evidence_serialization_preserves_data():
    candidates = [{'text': '合成证据\n保留原文', 'source': 'chat_summary'}]
    prompt = Service._build_profile_classification_prompt(person_id='synthetic', primary_name='Synthetic', aliases=['别名'], candidates=candidates)
    assert json.loads(prompt.split('证据列表：\n', 1)[1]) == candidates
