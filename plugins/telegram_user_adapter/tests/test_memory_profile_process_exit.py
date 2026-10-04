"""Real process exit around profile commit, no child cleanup handlers."""
import subprocess
import sys
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('phase', ['before', 'after'])
def test_profile_process_exit(tmp_path, phase):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    first = store.upsert_person_profile_snapshot('synthetic', 'old profile')
    store.close()
    code = '''import os, sys
from src.A_memorix.core.storage.metadata_store import MetadataStore
s = MetadataStore(data_dir=sys.argv[1]); s.connect()
if sys.argv[2] == 'before':
    original = s.get_latest_person_profile_snapshot
    def crash(pid):
        row = original(pid)
        assert row['profile_version'] == 2
        os._exit(73)
    s.get_latest_person_profile_snapshot = crash
result = s.upsert_person_profile_snapshot('synthetic', 'new profile', fact_claim_ids=['synthetic-claim'], evidence_fingerprint='synthetic-fingerprint')
assert result['profile_version'] == 2
os._exit(74)
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path), phase],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    assert result.returncode == (73 if phase == 'before' else 74)
    store.connect()
    try:
        latest = store.get_latest_person_profile_snapshot('synthetic')
        assert latest is not None
        if phase == 'before':
            assert latest == first
            retried = store.upsert_person_profile_snapshot('synthetic', 'new profile')
            assert retried['profile_version'] == 2
        else:
            assert latest['profile_version'] == 2
            assert latest['profile_text'] == 'new profile'
            assert latest['fact_claim_ids'] == ['synthetic-claim']
            assert latest['evidence_fingerprint'] == 'synthetic-fingerprint'
        assert store._conn.execute('SELECT COUNT(*) FROM person_profile_snapshots').fetchone()[0] == 2
        assert store._conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert store._conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        store.close()
