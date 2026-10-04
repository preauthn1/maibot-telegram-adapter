"""Actual profile refresh and SQLite snapshot persistence; retrieval/classification synthetic."""
import asyncio
import pytest
from typing import Any
from unittest.mock import AsyncMock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.person_profile_service import PersonProfileService
from src.A_memorix.core.utils import person_profile_service as module


def test_legacy_generation_snapshot_is_rebuilt(tmp_path, monkeypatch):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        current_version = module.PROFILE_GENERATION_VERSION
        monkeypatch.setattr(module, "PROFILE_GENERATION_VERSION", 2)
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
        monkeypatch.setattr(module, 'PROFILE_GENERATION_VERSION', current_version)
        second = asyncio.run(svc.query_person_profile(person_id='synthetic'))
        assert second['success'] and not second['from_cache']
        assert second['profile_version'] == first['profile_version'] + 1
        assert second['evidence_fingerprint'] != first['evidence_fingerprint']
        assert second['fact_claim_ids'] == first['fact_claim_ids']
        store.close(); store.connect()
        cached = asyncio.run(svc.query_person_profile(person_id='synthetic'))
        assert cached['from_cache'] and cached['snapshot_id'] == second['snapshot_id']
        assert classifier.await_count == 2
    finally:
        store.close()
