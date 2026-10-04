"""Renewing an obsolete snapshot must not return success for another version."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_obsolete_snapshot_renewal_is_rejected_without_changes(tmp_path):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        old = store.upsert_person_profile_snapshot('synthetic', 'old', expires_at=100)
        latest = store.upsert_person_profile_snapshot('synthetic', 'new', expires_at=200)
        before = [tuple(r) for r in store._conn.execute(
            'SELECT * FROM person_profile_snapshots ORDER BY snapshot_id').fetchall()]
        with pytest.raises(ValueError, match='^obsolete_profile_snapshot$'):
            store.refresh_person_profile_snapshot_cache(old['snapshot_id'], expires_at=999,
                                                        source_note='should roll back')
        assert not store._conn.in_transaction
        store._conn.commit()
        store.close(); store.connect()
        after = [tuple(r) for r in store._conn.execute(
            'SELECT * FROM person_profile_snapshots ORDER BY snapshot_id').fetchall()]
        assert after == before
        renewed = store.refresh_person_profile_snapshot_cache(latest['snapshot_id'], expires_at=999)
        assert renewed['snapshot_id'] == latest['snapshot_id']
        assert renewed['expires_at'] == 999
        store.close(); store.connect()
        assert store.get_latest_person_profile_snapshot('synthetic') == renewed
    finally:
        store.close()
