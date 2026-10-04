"""RAISE(FAIL) retains statement changes unless enqueue rolls back its transaction."""
import sqlite3
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


@pytest.mark.parametrize('existing', [False, True])
def test_enqueue_trigger_failure_rolls_back(tmp_path, existing):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        if existing:
            store.enqueue_paragraph_vector_backfill('synthetic', error='original')
        before = [tuple(r) for r in store._conn.execute('SELECT * FROM paragraph_vector_backfill')]
        event = 'UPDATE' if existing else 'INSERT'
        store._conn.execute(f"CREATE TRIGGER fail_enqueue AFTER {event} ON paragraph_vector_backfill BEGIN SELECT RAISE(FAIL, 'synthetic queue failure'); END")
        store._conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            store.enqueue_paragraph_vector_backfill('synthetic', error='changed')
        assert not store._conn.in_transaction
        assert [tuple(r) for r in store._conn.execute('SELECT * FROM paragraph_vector_backfill')] == before
        store._conn.execute('DROP TRIGGER fail_enqueue')
        store._conn.commit()
        store.close(); store.connect()
        assert [tuple(r) for r in store._conn.execute('SELECT * FROM paragraph_vector_backfill')] == before
        store.enqueue_paragraph_vector_backfill('synthetic', error='recovered')
        store.close(); store.connect()
        tasks = store.fetch_paragraph_vector_backfill_batch()
        assert len(tasks) == 1 and tasks[0]['last_error'] == 'recovered'
    finally:
        store.close()
