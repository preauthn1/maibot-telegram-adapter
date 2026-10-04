"""Real process exits around SQLite profile-cache renewal commit."""
import subprocess
import sys
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_profile_renewal_process_exit(tmp_path, phase):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    first = store.upsert_person_profile_snapshot('synthetic', 'synthetic profile',
        expires_at=100, updated_at=10, source_note='original')
    store.close()
    code = '''import os, sys
from src.A_memorix.core.storage.metadata_store import MetadataStore
s = MetadataStore(data_dir=sys.argv[1]); s.connect()
if sys.argv[2] == 'before':
    original = s.get_latest_person_profile_snapshot
    def crash(pid):
        row = original(pid)
        assert row['expires_at'] == 200 and row['source_note'] == 'renewed'
        os._exit(73)
    s.get_latest_person_profile_snapshot = crash
result = s.refresh_person_profile_snapshot_cache(int(sys.argv[3]), expires_at=200, updated_at=20, source_note='renewed')
assert result['expires_at'] == 200
os._exit(74)
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path), phase,
        str(first['snapshot_id'])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    assert result.returncode == (73 if phase == 'before' else 74)
    store.connect()
    try:
        latest = store.get_latest_person_profile_snapshot('synthetic')
        expected = dict(first)
        if phase == 'after':
            expected.update(expires_at=200, updated_at=20, source_note='renewed')
        assert latest == expected
        if phase == 'before':
            renewed = store.refresh_person_profile_snapshot_cache(first['snapshot_id'],
                expires_at=200, updated_at=20, source_note='renewed')
            expected.update(expires_at=200, updated_at=20, source_note='renewed')
            assert renewed == expected
        store.close(); store.connect()
        assert store.get_latest_person_profile_snapshot('synthetic') == expected
        assert store._conn.execute('SELECT COUNT(*) FROM person_profile_snapshots').fetchone()[0] == 1
        assert store._conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert store._conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        store.close()
