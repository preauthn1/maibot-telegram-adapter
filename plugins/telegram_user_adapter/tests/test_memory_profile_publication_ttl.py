"""Actual profile refresh and SQLite snapshot persistence; retrieval/classification synthetic."""
import asyncio
import pytest
from typing import Any
from unittest.mock import AsyncMock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.person_profile_service import PersonProfileService


def test_slow_classification_gets_full_ttl_at_publication(tmp_path, monkeypatch):
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
        clock = [100.0]
        monkeypatch.setattr('src.A_memorix.core.utils.person_profile_service.time.time', lambda: clock[0])
        async def slow_classification(**kwargs):
            await asyncio.sleep(0)
            clock[0] = 200.0
            return buckets
        classifier.side_effect = slow_classification
        result = asyncio.run(svc.query_person_profile(person_id='synthetic', ttl_seconds=30, force_refresh=True))
        assert result['expires_at'] == 230.0
        assert not svc._is_snapshot_stale(result, 30)
        store.close(); store.connect()
        saved = store.get_latest_person_profile_snapshot('synthetic')
        assert saved is not None and saved['expires_at'] == 230.0
        cached = asyncio.run(svc.query_person_profile(person_id='synthetic', ttl_seconds=30))
        assert cached['from_cache']
        assert classifier.await_count == 1
    finally:
        store.close()
