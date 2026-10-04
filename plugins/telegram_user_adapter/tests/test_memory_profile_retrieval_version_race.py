"""Actual profile refresh and SQLite snapshot persistence; retrieval/classification synthetic."""
import asyncio
import pytest
from typing import Any
from unittest.mock import AsyncMock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.person_profile_service import PersonProfileService


def test_new_snapshot_during_retrieval_is_used(tmp_path, monkeypatch):
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
        newer = {}
        async def publish_during_retrieval(*args, **kwargs):
            await asyncio.sleep(0)
            newer.update(store.upsert_person_profile_snapshot(
                'synthetic', first['profile_text'], aliases=first['aliases'],
                relation_edges=first['relation_edges'], vector_evidence=first['vector_evidence'],
                evidence_ids=first['evidence_ids'], fact_claim_ids=first['fact_claim_ids'],
                evidence_fingerprint=first['evidence_fingerprint']))
            return []
        monkeypatch.setattr(svc, '_collect_vector_evidence', publish_during_retrieval)
        result = asyncio.run(svc.query_person_profile(person_id='synthetic', force_refresh=True))
        assert result['success'] and result['evidence_unchanged']
        assert result['snapshot_id'] == newer['snapshot_id']
        assert result['profile_version'] == 2
        assert classifier.await_count == 1
        store.close(); store.connect()
        latest = store.get_latest_person_profile_snapshot('synthetic')
        assert latest['snapshot_id'] == newer['snapshot_id']
        assert latest['profile_text'] == first['profile_text']
        assert store._conn.execute('SELECT COUNT(*) FROM person_profile_snapshots').fetchone()[0] == 2
    finally:
        store.close()
