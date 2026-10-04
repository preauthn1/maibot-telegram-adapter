"""Real SQLite statement failure cannot leak a profile version."""
import sqlite3
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_failed_snapshot_insert_rolls_back_and_retry_reuses_version(tmp_path):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        first = store.upsert_person_profile_snapshot('synthetic', 'old synthetic profile')
        store._conn.execute("""CREATE TRIGGER fail_profile AFTER INSERT ON person_profile_snapshots
            WHEN NEW.profile_version = 2
            BEGIN SELECT RAISE(FAIL, 'synthetic snapshot failure'); END""")
        store._conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            store.upsert_person_profile_snapshot('synthetic', 'new synthetic profile')
        assert not store._conn.in_transaction
        store._conn.commit()
        store.close(); store.connect()
        assert store.get_latest_person_profile_snapshot('synthetic') == first
        assert store._conn.execute('SELECT COUNT(*) FROM person_profile_snapshots').fetchone()[0] == 1
        store._conn.execute('DROP TRIGGER fail_profile')
        store._conn.commit()
        second = store.upsert_person_profile_snapshot('synthetic', 'new synthetic profile')
        assert second['profile_version'] == 2
        store.close(); store.connect()
        assert store.get_latest_person_profile_snapshot('synthetic') == second
    finally:
        store.close()
