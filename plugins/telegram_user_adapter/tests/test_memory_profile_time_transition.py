"""Clock-only claim transitions invalidate a still-fresh real SQLite profile."""
import asyncio
from unittest.mock import AsyncMock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.person_profile_service import PersonProfileService


@pytest.mark.parametrize('transition', ['expires', 'activates'])
def test_profile_clock_transition(tmp_path, monkeypatch, transition):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    clock = [50.0]
    monkeypatch.setattr('src.A_memorix.core.utils.person_profile_service.time.time', lambda: clock[0])
    try:
        svc = PersonProfileService(store)
        monkeypatch.setattr(svc, 'get_person_aliases', lambda pid: (['Synthetic'], 'Synthetic', []))
        monkeypatch.setattr(svc, '_collect_relation_evidence', lambda *a, **kw: [])
        monkeypatch.setattr(svc, '_collect_vector_evidence', AsyncMock(return_value=[]))
        classifier = AsyncMock(return_value={key: [] for key in (
            'identity_settings', 'relationship_settings', 'stable_facts',
            'interaction_preferences', 'recent_interactions', 'uncertain_notes')})
        monkeypatch.setattr(svc, '_classify_profile_evidence', classifier)
        claim = store.upsert_fact_claim(scope_type='person', scope_id='synthetic', fact_key='temporal',
            value_text='SYNTHETIC_TIMED_FACT', authority='manual', stability='stable',
            valid_from=0 if transition == 'expires' else 100,
            valid_to=100 if transition == 'expires' else 200)
        first = asyncio.run(svc.query_person_profile(person_id='synthetic', force_refresh=True, ttl_seconds=1000))
        assert ('SYNTHETIC_TIMED_FACT' in first['profile_text']) == (transition == 'expires')
        # No facts are written between these two reads; the snapshot TTL is still fresh.
        assert not svc._is_snapshot_stale(first, 1000)
        clock[0] = 100.0
        assert not svc._is_snapshot_stale(first, 1000)
        second = asyncio.run(svc.query_person_profile(person_id='synthetic', ttl_seconds=1000))
        assert second['success'] and not second['from_cache']
        assert ('SYNTHETIC_TIMED_FACT' in second['profile_text']) == (transition == 'activates')
        assert second['fact_claim_ids'] == ([claim['claim_id']] if transition == 'activates' else [])
        store.close(); store.connect()
        cached = asyncio.run(svc.query_person_profile(person_id='synthetic', ttl_seconds=1000))
        assert cached['from_cache'] and cached['profile_text'] == second['profile_text']
        assert classifier.await_count == 2
    finally:
        store.close()
