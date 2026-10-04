"""Real SQLite profile candidate selection; not final rendered persona."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('point', [True, float('nan'), float('inf'), -float('inf'), 'invalid'])
def test_profile_invalid_time(tmp_path, point):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        with pytest.raises(ValueError, match='^invalid_fact_time$'):
            s.list_person_profile_fact_claims('synthetic', effective_at=point)
    finally: s.close()


def test_profile_scope_authority_and_time(tmp_path):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        def add(key, **kw):
            args = dict(scope_type='person', scope_id='synthetic', fact_key=key,
                        value_text=key, authority='manual', stability='stable',
                        valid_from=0, valid_to=100)
            args.update(kw)
            return s.upsert_fact_claim(**args)['claim_id']
        stable = add('stable')
        uncertain = add('uncertain', authority='summary_derived', stability='uncertain', profile_section='uncertain_notes')
        add('untrusted-stable', authority='summary_derived')
        add('other-person', scope_id='other')
        add('expired', valid_from=-100, valid_to=0)
        s.close(); s.connect()
        assert {r['claim_id'] for r in s.list_person_profile_fact_claims('synthetic', effective_at=0)} == {stable, uncertain}
        assert {r['claim_id'] for r in s.list_current_person_fact_claims('synthetic', effective_at=0)} == {stable}
        assert s.list_person_profile_fact_claims('synthetic', effective_at=100) == []
    finally: s.close()
