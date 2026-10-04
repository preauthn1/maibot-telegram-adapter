"""Profile storage rejects invalid timestamps before writes."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('api', ['insert', 'renew'])
@pytest.mark.parametrize('field', ['updated_at', 'expires_at'])
@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), -float('inf'), 'invalid'])
def test_invalid_profile_storage_time(tmp_path, api, field, value):
    s = MetadataStore(data_dir=tmp_path); s.connect()
    try:
        original = s.upsert_person_profile_snapshot('synthetic', 'original', updated_at=0, expires_at=100)
        changes = s._conn.total_changes
        with pytest.raises(ValueError, match='^invalid_profile_time$'):
            if api == 'insert':
                s.upsert_person_profile_snapshot('synthetic', 'changed', **{field: value})
            else:
                args = dict(expires_at=200, updated_at=20)
                args[field] = value
                s.refresh_person_profile_snapshot_cache(original['snapshot_id'], **args)
        assert s._conn.total_changes == changes
        assert not s._conn.in_transaction
        s.close(); s.connect()
        assert s.get_latest_person_profile_snapshot('synthetic') == original
    finally: s.close()
