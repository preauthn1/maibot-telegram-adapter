"""Real SQLite query time validation and interval boundaries."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('api', ['general', 'person'])
@pytest.mark.parametrize('point', [True, float('nan'), float('inf'), -float('inf'), 'invalid'])
def test_invalid_query_time(tmp_path, api, point):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        with pytest.raises(ValueError, match='^invalid_fact_time$'):
            if api == 'general':
                s.list_fact_claims(scope_type='person', scope_id='synthetic', effective_at=point)
            else:
                s.list_current_person_fact_claims('synthetic', effective_at=point)
    finally: s.close()


def test_general_interval_boundaries(tmp_path):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        c = s.upsert_fact_claim(scope_type='person', scope_id='synthetic', fact_key='key',
            value_text='synthetic', valid_from=0, valid_to=100)
        s.close(); s.connect()
        for point, expected in [(-1, []), (0, [c['claim_id']]), (99, [c['claim_id']]), (100, [])]:
            rows = s.list_fact_claims(scope_type='person', scope_id='synthetic', effective_at=point)
            assert [r['claim_id'] for r in rows] == expected
    finally: s.close()
