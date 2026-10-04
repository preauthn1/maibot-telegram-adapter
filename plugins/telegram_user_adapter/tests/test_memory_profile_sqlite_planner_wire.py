"""Actual profile refresh and SQLite snapshot persistence; retrieval/classification synthetic."""
import asyncio
import pytest
from typing import Any
from unittest.mock import AsyncMock
from types import SimpleNamespace
from src.maisaka.memory import person_profile as planner
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.person_profile_service import PersonProfileService


def test_sqlite_override_reaches_actual_planner(tmp_path, monkeypatch):
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
        monkeypatch.setattr(planner, 'global_config', SimpleNamespace(a_memorix=SimpleNamespace(
            integration=SimpleNamespace(enable_person_profile_injection=True, person_profile_injection_max_profiles=3))))
        candidate = SimpleNamespace(person_id='synthetic', person_name='Synthetic', user_id='synthetic-user')
        monkeypatch.setattr(planner, 'collect_person_profile_candidates', lambda *a, **kw: [candidate])
        calls = []
        async def profile_admin(**kwargs):
            calls.append(kwargs)
            assert kwargs['action'] == 'query'
            return await svc.query_person_profile(person_id=kwargs['person_id'])
        monkeypatch.setattr(planner, 'memory_service', SimpleNamespace(profile_admin=profile_admin))
        def inject():
            return asyncio.run(planner.build_person_profile_injection_messages(anchor_message=object()))
        common: dict[str, Any] = dict(scope_type='person', scope_id='synthetic', fact_key='favorite',
                      cardinality='single', authority='manual', stability='stable')
        old = store.upsert_fact_claim(**common, value_text='SYNTHETIC_OLD_VALUE')
        first = asyncio.run(svc.query_person_profile(person_id='synthetic', force_refresh=True))
        assert first['success'] and 'SYNTHETIC_OLD_VALUE' in first['profile_text']
        before = store.get_latest_person_profile_snapshot('synthetic')
        store.set_person_profile_override('other', 'SYNTHETIC_OTHER_OVERRIDE')
        store.set_person_profile_override('synthetic', 'SYNTHETIC_MANUAL_OVERRIDE')
        store.close(); store.connect()
        manual = asyncio.run(svc.query_person_profile(person_id='synthetic'))
        assert manual['from_cache'] and manual['has_manual_override']
        assert manual['profile_source'] == 'manual_override'
        assert manual['profile_text'] == 'SYNTHETIC_MANUAL_OVERRIDE'
        assert manual['auto_profile_text'] == first['profile_text']
        messages = inject()
        assert len(messages) == 1
        block = messages[0]
        assert 'SYNTHETIC_MANUAL_OVERRIDE' in block
        assert 'SYNTHETIC_OLD_VALUE' not in block
        assert 'SYNTHETIC_OTHER_OVERRIDE' not in block
        assert store.get_latest_person_profile_snapshot('synthetic') == before
        store.set_person_profile_override('synthetic', '')
        store.close(); store.connect()
        restored = asyncio.run(svc.query_person_profile(person_id='synthetic'))
        assert restored['from_cache'] and not restored['has_manual_override']
        assert restored['profile_source'] == 'auto_snapshot'
        assert restored['profile_text'] == first['profile_text']
        assert store.get_latest_person_profile_snapshot('synthetic') == before
        restored_messages = inject()
        assert len(restored_messages) == 1
        assert 'SYNTHETIC_OLD_VALUE' in restored_messages[0]
        assert 'SYNTHETIC_MANUAL_OVERRIDE' not in restored_messages[0]
        assert 'SYNTHETIC_OTHER_OVERRIDE' not in restored_messages[0]
        assert store.get_latest_person_profile_snapshot('synthetic') == before
        assert len(calls) == 2
        assert all(call == dict(action='query', person_id='synthetic', limit=planner.PROFILE_QUERY_LIMIT) for call in calls)
        assert classifier.await_count == 1
    finally:
        store.close()
