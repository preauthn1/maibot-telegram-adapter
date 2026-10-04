"""Profile creation and renewal remain subordinate to an outer transaction."""
import asyncio
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('failure_type', [OSError, asyncio.CancelledError])
def test_profile_operations_obey_outer_rollback(tmp_path, failure_type):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        original = store.upsert_person_profile_snapshot('synthetic', 'original', expires_at=100)
        failure = failure_type('synthetic outer failure')
        with pytest.raises(failure_type) as caught:
            with store.transaction(immediate=True):
                created = store.upsert_person_profile_snapshot('synthetic', 'new', expires_at=200)
                renewed = store.refresh_person_profile_snapshot_cache(created['snapshot_id'], expires_at=300)
                assert renewed['expires_at'] == 300
                raise failure
        assert caught.value is failure
        conn = store._conn
        assert conn is not None and not conn.in_transaction
        conn.commit()
        store.close(); store.connect()
        assert store.get_latest_person_profile_snapshot('synthetic') == original
        conn = store._conn
        assert conn is not None
        assert conn.execute('SELECT COUNT(*) FROM person_profile_snapshots').fetchone()[0] == 1
        with store.transaction(immediate=True):
            created = store.upsert_person_profile_snapshot('synthetic', 'new', expires_at=200)
            renewed = store.refresh_person_profile_snapshot_cache(created['snapshot_id'], expires_at=300)
        assert renewed['profile_version'] == 2
        store.close(); store.connect()
        assert store.get_latest_person_profile_snapshot('synthetic') == renewed
    finally:
        store.close()
