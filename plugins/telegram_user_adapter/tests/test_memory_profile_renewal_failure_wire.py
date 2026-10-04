"""Actual profile refresh and SQLite snapshot persistence; retrieval/classification synthetic."""
import asyncio
import sqlite3
import pytest
from typing import Any
from unittest.mock import AsyncMock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.person_profile_service import PersonProfileService


def test_unchanged_evidence_renewal_failure_and_retry(tmp_path, monkeypatch):
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
        before = store.get_latest_person_profile_snapshot('synthetic')
        store._conn.execute("CREATE TRIGGER fail_renewal_wire AFTER UPDATE ON person_profile_snapshots BEGIN SELECT RAISE(FAIL, 'synthetic renewal failure'); END")
        store._conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            asyncio.run(svc.query_person_profile(person_id='synthetic', force_refresh=True, source_note='renewed'))
        assert classifier.await_count == 1
        assert not store._conn.in_transaction
        store._conn.commit()
        store.close(); store.connect()
        assert store.get_latest_person_profile_snapshot('synthetic') == before
        store._conn.execute('DROP TRIGGER fail_renewal_wire')
        store._conn.commit()
        renewed = asyncio.run(svc.query_person_profile(person_id='synthetic', force_refresh=True, source_note='renewed'))
        assert renewed['success'] and renewed['evidence_unchanged']
        assert renewed['snapshot_id'] == first['snapshot_id']
        assert renewed['profile_version'] == first['profile_version']
        assert renewed['profile_text'] == first['profile_text']
        assert renewed['source_note'] == 'renewed'
        store.close(); store.connect()
        cached = asyncio.run(svc.query_person_profile(person_id='synthetic'))
        assert cached['from_cache'] and cached['source_note'] == 'renewed'
        assert classifier.await_count == 1
        assert store._conn.execute('SELECT COUNT(*) FROM person_profile_snapshots').fetchone()[0] == 1
    finally:
        store.close()
