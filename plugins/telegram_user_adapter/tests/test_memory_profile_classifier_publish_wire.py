"""Actual classifier/parser/profile publication with only synthetic provider and retrieval."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils import person_profile_service as module


def test_mixed_provider_json_to_real_snapshot(tmp_path, monkeypatch):
    store = MetadataStore(data_dir=tmp_path); store.connect()
    try:
        svc = module.PersonProfileService(store)
        monkeypatch.setattr(svc, 'get_person_aliases', lambda pid: (['Synthetic'], 'Synthetic', ['SYNTHETIC_EVIDENCE']))
        monkeypatch.setattr(svc, '_collect_relation_evidence', lambda *a, **kw: [])
        monkeypatch.setattr(svc, '_collect_vector_evidence', AsyncMock(return_value=[]))
        model = SimpleNamespace(task_name='synthetic', selected_model_name='synthetic',
                                task_config=SimpleNamespace(model_list=['synthetic']))
        monkeypatch.setattr(svc, '_resolve_profile_classification_model', lambda: model)
        provider = AsyncMock(return_value=SimpleNamespace(success=True, completion=SimpleNamespace(
            response=json.dumps({'stable_facts': ['SYNTHETIC_MODEL_TEXT',
                {'value': 'SYNTHETIC_BAD_OBJECT'}, ['SYNTHETIC_BAD_LIST'], 987654321, True]}))))
        monkeypatch.setattr(module, 'generate_with_resolved_model', provider)
        claim = store.upsert_fact_claim(scope_type='person', scope_id='synthetic', fact_key='verified',
            value_text='SYNTHETIC_TRUSTED_FACT', authority='manual', stability='stable')
        result = asyncio.run(svc.query_person_profile(person_id='synthetic', force_refresh=True))
        assert result['success']
        text = result['profile_text']
        assert 'SYNTHETIC_TRUSTED_FACT' in text and 'SYNTHETIC_MODEL_TEXT' in text
        for invalid in ('SYNTHETIC_BAD_OBJECT', 'SYNTHETIC_BAD_LIST', '987654321', 'True'):
            assert invalid not in text
        assert result['fact_claim_ids'] == [claim['claim_id']]
        store.close(); store.connect()
        saved = store.get_latest_person_profile_snapshot('synthetic')
        assert saved is not None and saved['profile_text'] == text
        cached = asyncio.run(svc.query_person_profile(person_id='synthetic'))
        assert cached['from_cache'] and cached['profile_text'] == text
        assert provider.await_count == 1
    finally:
        store.close()
