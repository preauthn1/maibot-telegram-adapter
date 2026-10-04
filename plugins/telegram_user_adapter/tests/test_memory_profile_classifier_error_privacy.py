"""Exercise actual classifier fallback without logging provider exception bodies."""
import asyncio
from unittest.mock import AsyncMock, Mock
import pytest
from src.A_memorix.core.utils import person_profile_service as module


@pytest.mark.parametrize('stage', ['generation', 'resolution'])
def test_classifier_exception_privacy(monkeypatch, stage):
    svc = object.__new__(module.PersonProfileService)
    svc.plugin_config = {}
    logger = Mock()
    monkeypatch.setattr(module, 'logger', logger)
    marker = 'SYNTHETIC_PRIVATE_PROVIDER_DETAIL'
    if stage == 'resolution':
        monkeypatch.setattr(module, 'get_text_generation_model_tasks', Mock(side_effect=OSError(marker)))
        assert svc._resolve_profile_classification_model() is None
    else:
        fallback = {'uncertain_notes': ['synthetic evidence']}
        monkeypatch.setattr(svc, '_classify_profile_evidence_rule_based', lambda **kw: fallback)
        monkeypatch.setattr(svc, '_build_profile_classification_candidates', lambda **kw: ['synthetic'])
        monkeypatch.setattr(svc, '_resolve_profile_classification_model', lambda: object())
        monkeypatch.setattr(svc, '_build_profile_classification_prompt', lambda **kw: 'synthetic prompt')
        monkeypatch.setattr(module, 'generate_with_resolved_model', AsyncMock(side_effect=OSError(marker)))
        result = asyncio.run(svc._classify_profile_evidence(person_id='synthetic', primary_name='Synthetic',
            aliases=[], relation_edges=[], vector_evidence=[], memory_traits=[]))
        assert result == fallback
    messages = repr(logger.mock_calls)
    assert marker not in messages
    assert 'OSError' in messages
