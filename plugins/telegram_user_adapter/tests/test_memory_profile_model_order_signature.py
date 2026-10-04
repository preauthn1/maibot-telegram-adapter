"""Model priority order is semantic even when evidence order is not."""
from types import SimpleNamespace
from src.A_memorix.core.utils.person_profile_service import PersonProfileService


def test_model_priority_changes_profile_fingerprint(monkeypatch):
    svc = object.__new__(PersonProfileService)
    svc.plugin_config = {}
    config = SimpleNamespace(model_list=['synthetic-a', 'synthetic-b'])
    model = SimpleNamespace(task_name='synthetic', selected_model_name='', task_config=config)
    monkeypatch.setattr(svc, '_resolve_profile_classification_model', lambda: model)
    args = dict(person_id='synthetic', primary_name='Synthetic', aliases=['b', 'a'],
                memory_traits=[], relation_edges=[], vector_evidence=[], fact_claims=[])
    original = svc._profile_evidence_fingerprint(**args)
    args['aliases'] = ['a', 'b']
    assert svc._profile_evidence_fingerprint(**args) == original
    config.model_list = ['synthetic-b', 'synthetic-a']
    assert svc._profile_evidence_fingerprint(**args) != original
    config.model_list = ['synthetic-a', 'synthetic-b']
    assert svc._profile_evidence_fingerprint(**args) == original
