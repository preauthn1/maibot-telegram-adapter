"""SQLite AFTER UPDATE failure must not persist failed cache renewal."""
import sqlite3
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_cache_renewal_failure_rolls_back(tmp_path):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        first = store.upsert_person_profile_snapshot('synthetic', 'synthetic profile',
            expires_at=100, updated_at=10, source_note='original')
        store._conn.execute("""CREATE TRIGGER fail_renewal AFTER UPDATE ON person_profile_snapshots
            BEGIN SELECT RAISE(FAIL, 'synthetic renewal failure'); END""")
        store._conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            store.refresh_person_profile_snapshot_cache(first['snapshot_id'],
                expires_at=200, updated_at=20, source_note='changed')
        assert not store._conn.in_transaction
        store._conn.commit()
        store.close(); store.connect()
        assert store.get_latest_person_profile_snapshot('synthetic') == first
        store._conn.execute('DROP TRIGGER fail_renewal')
        store._conn.commit()
        renewed = store.refresh_person_profile_snapshot_cache(first['snapshot_id'],
            expires_at=200, updated_at=20, source_note='changed')
        assert renewed['snapshot_id'] == first['snapshot_id']
        assert renewed['profile_version'] == first['profile_version']
        assert renewed['expires_at'] == 200
        assert renewed['updated_at'] == 20
        assert renewed['source_note'] == 'changed'
        store.close(); store.connect()
        assert store.get_latest_person_profile_snapshot('synthetic') == renewed
    finally:
        store.close()
