"""Real SQLite claim time validation before mutation."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('field', ['observed_at', 'valid_from', 'valid_to'])
@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), -float('inf'), 'synthetic-invalid'])
def test_invalid_claim_time(tmp_path, field, value):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        before = s._conn.total_changes
        with pytest.raises(ValueError, match='^invalid_fact_time$'):
            s.upsert_fact_claim(scope_type='person', scope_id='synthetic', fact_key='key',
                value_text='合成事实', **{field: value})
        assert s._conn.total_changes == before
        s.close(); s.connect()
        assert s.list_fact_claims(scope_type='person', scope_id='synthetic') == []
    finally:
        s.close()


def test_valid_claim_time(tmp_path):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        result = s.upsert_fact_claim(scope_type='person', scope_id='synthetic', fact_key='key',
            value_text='合成事实', observed_at=0, valid_from='0', valid_to='100')
        s.close(); s.connect()
        row = s.get_fact_claim(result['claim_id'])
        assert row['first_observed_at'] == 0
        assert row['valid_from'] == 0 and row['valid_to'] == 100
    finally:
        s.close()
