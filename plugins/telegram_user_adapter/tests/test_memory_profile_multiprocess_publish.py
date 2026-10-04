"""Independent processes allocate profile versions against real SQLite."""
import json
import subprocess
import sys
import time
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_profile_multiprocess_publish(tmp_path):
    store = MetadataStore(data_dir=tmp_path)
    store.connect(); store.close()
    code = '''import json,sys,time
from pathlib import Path
from src.A_memorix.core.storage.metadata_store import MetadataStore
root=Path(sys.argv[1]); label=sys.argv[2]
s=MetadataStore(data_dir=root); s.connect()
(root/(label+'.ready')).touch()
deadline=time.monotonic()+15
while not (root/'go').exists():
    if time.monotonic()>deadline: raise TimeoutError('synthetic barrier')
    time.sleep(0.01)
def trace(sql):
    if sql.lstrip().startswith('INSERT INTO person_profile_snapshots'): time.sleep(0.1)
s._conn.set_trace_callback(trace)
rows=[s.upsert_person_profile_snapshot('synthetic',label+'-'+str(i)) for i in range(3)]
(root/(label+'.json')).write_text(json.dumps(rows))
s.close()
'''
    processes = []
    try:
        for label in ('a', 'b'):
            processes.append(subprocess.Popen([sys.executable, '-c', code, str(tmp_path), label],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        deadline = time.monotonic() + 20
        while not all((tmp_path / (label + '.ready')).exists() for label in ('a', 'b')):
            assert all(p.poll() is None for p in processes), 'worker exited before barrier'
            assert time.monotonic() < deadline, 'worker barrier timeout'
            time.sleep(0.01)
        (tmp_path / 'go').touch()
        for process in processes:
            assert process.wait(timeout=20) == 0
        results = []
        for label in ('a', 'b'):
            rows = json.loads((tmp_path / (label + '.json')).read_text())
            assert [r['profile_text'] for r in rows] == [label + '-' + str(i) for i in range(3)]
            results.extend(rows)
        assert sorted(r['profile_version'] for r in results) == list(range(1, 7))
        assert len({r['snapshot_id'] for r in results}) == 6
        store.connect()
        conn = store._conn
        assert conn is not None
        persisted = conn.execute('SELECT snapshot_id, profile_version, profile_text FROM person_profile_snapshots').fetchall()
        assert {tuple(r) for r in persisted} == {(r['snapshot_id'], r['profile_version'], r['profile_text']) for r in results}
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        store.close()
