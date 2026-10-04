"""Person claim confidence boundary; storage call spy, no production data."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


@pytest.mark.parametrize('trust', ['manual_confirmed', ''])
@pytest.mark.parametrize('score', [0, 0.25, 0.9, None])
def test_person_claim_confidence_preserves_zero(trust, score):
    storage = SimpleNamespace(transaction=lambda **kw: nullcontext(), upsert_fact_claim=Mock(return_value={'claim_id': 'synthetic'}))
    svc = SimpleNamespace(metadata_store=storage)
    result = MemoryIngestService._write_person_fact_claims(
        svc, paragraph_hash='synthetic-paragraph', content='合成人物事实',
        person_ids=['synthetic-person'], timestamp=None,
        metadata={'fact_claim': {'trust': trust, 'confidence': score}})
    expected = (1.0 if trust else 0.5) if score is None else score
    if not trust: expected = min(0.5, expected)
    assert result == ['synthetic']
    assert storage.upsert_fact_claim.call_args.kwargs['confidence'] == expected
