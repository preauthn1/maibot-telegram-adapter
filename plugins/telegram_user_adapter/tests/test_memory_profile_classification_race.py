"""Actual profile refresh and SQLite snapshot persistence; retrieval/classification synthetic."""
import asyncio
import pytest
from typing import Any
from unittest.mock import AsyncMock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.person_profile_service import PersonProfileService


def test_correction_during_classification_uses_current_facts(tmp_path, monkeypatch):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        svc = PersonProfileService(store)
        monkeypatch.setattr(svc, 'get_person_aliases', lambda pid: (['Synthetic'], 'Synthetic', []))
        monkeypatch.setattr(svc, '_collect_relation_evidence', lambda *a, **kw: [])
        monkeypatch.setattr(svc, '_collect_vector_evidence', AsyncMock(return_value=[]))
        buckets = {k: [] for k in ('identity_settings', 'relationship_settings', 'stable_facts',
                                  'interaction_preferences', 'recent_interactions', 'uncertain_notes')}
        classifier = AsyncMock(return_value=buckets)
        monkeypatch.setattr(svc, '_classify_profile_evidence', classifier)
        common: dict[str, Any] = dict(scope_type='person', scope_id='synthetic', fact_key='favorite',
                      cardinality='single', authority='manual', stability='stable')
        old = store.upsert_fact_claim(**common, value_text='SYNTHETIC_OLD_VALUE')
        first = asyncio.run(svc.query_person_profile(person_id='synthetic', force_refresh=True))
        assert first['success'] and 'SYNTHETIC_OLD_VALUE' in first['profile_text']
        new = {}
        async def correct_during_classification(**kwargs):
            await asyncio.sleep(0)
            new.update(store.upsert_fact_claim(**common, value_text='SYNTHETIC_NEW_VALUE',
                                               supersedes_claim_ids=[old['claim_id']]))
            return buckets
        classifier.side_effect = correct_during_classification
        # Change generation input to force classification rather than fingerprint short-circuit.
        monkeypatch.setattr(svc, 'get_person_aliases', lambda pid: (['Synthetic2'], 'Synthetic2', []))
        second = asyncio.run(svc.query_person_profile(person_id='synthetic', force_refresh=True))
        classifier.side_effect = None
        assert second['success'] and not second['from_cache']
        assert 'SYNTHETIC_NEW_VALUE' in second['profile_text']
        assert 'SYNTHETIC_OLD_VALUE' not in second['profile_text']
        assert second['fact_claim_ids'] == [new['claim_id']]
        store.close(); store.connect()
        saved = store.get_latest_person_profile_snapshot('synthetic')
        assert saved is not None
        assert saved['profile_text'] == second['profile_text']
        cached = asyncio.run(svc.query_person_profile(person_id='synthetic'))
        assert cached['from_cache'] and cached['profile_text'] == second['profile_text']
        assert classifier.await_count == 2
        block = svc.format_persona_profile_block(cached)
        assert 'SYNTHETIC_NEW_VALUE' in block and 'SYNTHETIC_OLD_VALUE' not in block
    finally:
        store.close()
