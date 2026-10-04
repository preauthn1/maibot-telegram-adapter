"""Malformed model parameters use defaults, finite parameters retain clamping."""
import pytest
from src.A_memorix.core.utils.person_profile_service import PersonProfileService as Service

@pytest.mark.parametrize('value', [True, False, float('nan'), float('inf'), -float('inf'), None, 'invalid'])
@pytest.mark.parametrize('kind,default', [('max_tokens', 1200), ('temperature', 0.1)])
def test_invalid_model_config_defaults(value, kind, default):
    svc = object.__new__(Service)
    svc.plugin_config = {'person_profile': {'evidence_classification_' + kind: value}}
    assert getattr(svc, '_profile_classification_' + kind)() == default

@pytest.mark.parametrize('kind,value,expected', [('temperature', 0, 0), ('temperature', 3, 2),
    ('temperature', -1, 0), ('max_tokens', 64, 128), ('max_tokens', 40000, 32768),
    ('max_tokens', '2048', 2048)])
def test_finite_model_config_compatibility(kind, value, expected):
    svc = object.__new__(Service)
    svc.plugin_config = {'person_profile': {'evidence_classification_' + kind: value}}
    assert getattr(svc, '_profile_classification_' + kind)() == expected
