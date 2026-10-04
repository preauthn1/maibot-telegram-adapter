"""Only an explicit successful model receipt may enter profile parsing."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from src.A_memorix.core.utils import person_profile_service as module

@pytest.mark.parametrize('success', ['false', 'true', 1, {}, None, False, True])
def test_profile_classifier_strict_success(monkeypatch, success):
    svc = object.__new__(module.PersonProfileService)
    svc.plugin_config = {}
    fallback = {'uncertain_notes': ['synthetic fallback']}
    parsed = {'uncertain_notes': ['synthetic parsed']}
    monkeypatch.setattr(svc, '_classify_profile_evidence_rule_based', lambda **kw: fallback)
    monkeypatch.setattr(svc, '_build_profile_classification_candidates', lambda **kw: ['synthetic'])
    monkeypatch.setattr(svc, '_resolve_profile_classification_model', lambda: object())
    monkeypatch.setattr(svc, '_build_profile_classification_prompt', lambda **kw: 'synthetic')
    parser = Mock(return_value=parsed)
    monkeypatch.setattr(svc, '_parse_profile_classification_response', parser)
    merger = Mock(return_value=parsed)
    monkeypatch.setattr(svc, '_merge_profile_classification', merger)
    monkeypatch.setattr(module, 'generate_with_resolved_model', AsyncMock(return_value=SimpleNamespace(
        success=success, completion=SimpleNamespace(response='synthetic response'))))
    result = asyncio.run(svc._classify_profile_evidence(person_id='synthetic', primary_name='Synthetic',
        aliases=[], relation_edges=[], vector_evidence=[], memory_traits=[]))
    if success is True:
        assert result == parsed
        parser.assert_called_once_with('synthetic response')
        merger.assert_called_once_with(fallback, parsed)
    else:
        assert result == fallback
        parser.assert_not_called()
        merger.assert_not_called()
