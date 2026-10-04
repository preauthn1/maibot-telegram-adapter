"""Real SQLite failure bookkeeping must roll back on statement failure."""
import sqlite3
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_failed_bookkeeping_rolls_back(tmp_path):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        store.enqueue_paragraph_vector_backfill('synthetic')
        store.mark_paragraph_vector_backfill_running(['synthetic'])
        before = tuple(store._conn.execute('SELECT * FROM paragraph_vector_backfill').fetchone())
        store._conn.execute("CREATE TRIGGER fail_status AFTER UPDATE ON paragraph_vector_backfill WHEN NEW.status='failed' BEGIN SELECT RAISE(FAIL, 'synthetic'); END")
        store._conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            store.mark_paragraph_vector_backfill_failed('synthetic', 'attempt')
        assert not store._conn.in_transaction
        assert tuple(store._conn.execute('SELECT * FROM paragraph_vector_backfill').fetchone()) == before
        store._conn.execute('DROP TRIGGER fail_status'); store._conn.commit()
        store.close(); store.connect()
        assert tuple(store._conn.execute('SELECT * FROM paragraph_vector_backfill').fetchone()) == before
        store.mark_paragraph_vector_backfill_failed('synthetic', 'retry')
        store.close(); store.connect()
        task = store.fetch_paragraph_vector_backfill_batch()[0]
        assert task['status'] == 'failed' and task['retry_count'] == 1
        assert task['last_error'] == 'retry'
    finally:
        store.close()
