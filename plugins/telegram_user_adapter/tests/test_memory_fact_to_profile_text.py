"""Real SQLite -> profile collection/merge/render; no LLM or production data."""
from types import SimpleNamespace
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.utils.person_profile_service import PersonProfileService as Service


def test_supersession_reaches_profile_text(tmp_path, monkeypatch):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        monkeypatch.setattr('src.A_memorix.core.utils.person_profile_service.time.time', lambda: 50.0)
        args = dict(scope_type='person', scope_id='synthetic-person', fact_key='favorite',
                    cardinality='single', authority='manual', stability='stable', observed_at=1)
        old = store.upsert_fact_claim(**args, value_text='SYNTHETIC_OLD_VALUE')
        store.upsert_fact_claim(**args, value_text='SYNTHETIC_NEW_VALUE',
                                supersedes_claim_ids=[old['claim_id']])
        store.upsert_fact_claim(scope_type='person', scope_id='other-person', fact_key='other',
                               value_text='SYNTHETIC_OTHER_PERSON', authority='manual')
        store.close(); store.connect()
        svc = SimpleNamespace(metadata_store=store, _append_profile_bucket=Service._append_profile_bucket)
        buckets = {k: [] for k in ('identity_settings', 'relationship_settings', 'stable_facts',
                                   'interaction_preferences', 'recent_interactions', 'uncertain_notes')}
        buckets['stable_facts'] = ['SYNTHETIC_MODEL_GUESS']
        confined = Service._confine_untrusted_profile_buckets(svc, buckets)
        claims = Service._collect_person_fact_claims(svc, 'synthetic-person')
        merged = Service._merge_fact_claim_buckets(svc, confined, claims)
        assert merged['stable_facts'] == ['SYNTHETIC_NEW_VALUE']
        assert merged['uncertain_notes'] == ['SYNTHETIC_MODEL_GUESS']
        text = Service._build_profile_text(svc, 'synthetic-person', 'Synthetic', [], [], [], [], merged)
        assert 'SYNTHETIC_NEW_VALUE' in text and 'SYNTHETIC_MODEL_GUESS' in text
        assert 'SYNTHETIC_OLD_VALUE' not in text and 'SYNTHETIC_OTHER_PERSON' not in text
    finally:
        store.close()
