"""Snapshot publication requires a real readback, not a fabricated receipt."""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('mismatch', ['old', 'person', 'version', 'id'])
def test_mismatched_snapshot_readback_rolls_back(tmp_path, monkeypatch, mismatch):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        first = store.upsert_person_profile_snapshot('synthetic', 'old')
        readback = store.get_latest_person_profile_snapshot
        def wrong_readback(pid):
            if mismatch == 'old':
                return dict(first)
            result = dict(readback(pid))
            result[{'person': 'person_id', 'version': 'profile_version', 'id': 'snapshot_id'}[mismatch]] = 'other' if mismatch == 'person' else -1
            return result
        monkeypatch.setattr(store, 'get_latest_person_profile_snapshot', wrong_readback)
        with pytest.raises(RuntimeError, match='^profile_snapshot_readback_mismatch$'):
            store.upsert_person_profile_snapshot('synthetic', 'new')
        assert not store._conn.in_transaction
        store._conn.commit()
        monkeypatch.setattr(store, 'get_latest_person_profile_snapshot', readback)
        store.close(); store.connect()
        assert readback('synthetic') == first
        second = store.upsert_person_profile_snapshot('synthetic', 'new')
        assert second['profile_version'] == 2
        store.close(); store.connect()
        assert readback('synthetic') == second
    finally:
        store.close()
