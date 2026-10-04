"""Invalid person claim confidence never reaches storage; synthetic boundary test."""
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.A_memorix.core.runtime.services.ingest_service import MemoryIngestService


@pytest.mark.parametrize('trust', ['manual_confirmed', ''])
@pytest.mark.parametrize('score', [True, False, float('nan'), float('inf'), -float('inf'), -0.1, 1.1, 'SYNTHETIC_PRIVATE_BAD_SCORE'])
def test_invalid_person_claim_score(trust, score):
    storage = SimpleNamespace(transaction=lambda **kw: nullcontext(), upsert_fact_claim=Mock())
    with pytest.raises(ValueError, match='^invalid_person_fact_confidence$'):
        MemoryIngestService._write_person_fact_claims(
            SimpleNamespace(metadata_store=storage), paragraph_hash='synthetic',
            content='合成事实', person_ids=['person-a', 'person-b'], timestamp=None,
            metadata={'fact_claim': {'trust': trust, 'confidence': score}})
    storage.upsert_fact_claim.assert_not_called()


@pytest.mark.parametrize('trust', ['manual_confirmed', ''])
def test_numeric_string_person_claim_score(trust):
    storage = SimpleNamespace(transaction=lambda **kw: nullcontext(), upsert_fact_claim=Mock(return_value={'claim_id': 'synthetic'}))
    MemoryIngestService._write_person_fact_claims(
        SimpleNamespace(metadata_store=storage), paragraph_hash='synthetic',
        content='合成事实', person_ids=['person-a'], timestamp=None,
        metadata={'fact_claim': {'trust': trust, 'confidence': '0.25'}})
    assert storage.upsert_fact_claim.call_args.kwargs['confidence'] == 0.25
