"""Explicit empty classification must not resurrect discarded evidence."""
from unittest.mock import Mock
import pytest
from src.A_memorix.core.utils.person_profile_service import PersonProfileService as Service

@pytest.mark.parametrize('provided', [{}, None])
def test_empty_classification_differs_from_missing(monkeypatch, provided):
    svc = object.__new__(Service)
    fallback = Mock(return_value={'stable_facts': ['SYNTHETIC_DISCARDED_EVIDENCE']})
    monkeypatch.setattr(svc, '_classify_profile_evidence_rule_based', fallback)
    text = svc._build_profile_text('synthetic', 'Synthetic', [], [], [], [], provided)
    if provided is None:
        fallback.assert_called_once()
        assert 'SYNTHETIC_DISCARDED_EVIDENCE' in text
    else:
        fallback.assert_not_called()
        assert 'SYNTHETIC_DISCARDED_EVIDENCE' not in text
