"""Two real SQLite connections publish competing profile versions."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_concurrent_profile_versions(tmp_path):
    seed = MetadataStore(data_dir=tmp_path)
    seed.connect()
    seed.close()
    ready = Barrier(2)
    def publish(label):
        store = MetadataStore(data_dir=tmp_path)
        store.connect()
        conn = store._conn
        assert conn is not None
        def trace(sql):
            # Widen the read-before-write window without blocking a write-lock holder.
            if sql.lstrip().startswith('INSERT INTO person_profile_snapshots'):
                time.sleep(0.15)
        conn.set_trace_callback(trace)
        try:
            ready.wait(timeout=10)
            return store.upsert_person_profile_snapshot('synthetic', label)
        finally:
            store.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish, label) for label in ('synthetic-a', 'synthetic-b')]
        results = [f.result(timeout=20) for f in futures]
    assert [r['profile_text'] for r in results] == ['synthetic-a', 'synthetic-b']
    assert sorted(r['profile_version'] for r in results) == [1, 2]
    assert len({r['snapshot_id'] for r in results}) == 2
    seed.connect()
    try:
        rows = seed._conn.execute('SELECT profile_version, profile_text FROM person_profile_snapshots ORDER BY profile_version').fetchall()
        assert [r[0] for r in rows] == [1, 2]
        assert {r[1] for r in rows} == {'synthetic-a', 'synthetic-b'}
    finally:
        seed.close()
