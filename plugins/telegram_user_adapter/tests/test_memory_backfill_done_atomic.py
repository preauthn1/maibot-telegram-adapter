"""真实SQLite触发器使第二块确认失败；不得残留第一块更新。"""
import sqlite3
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_done_chunks_rollback(tmp_path):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        ids=[f'synthetic-{i:04d}' for i in range(501)]
        # 队列表夹具，不创建或访问真实聊天内容。
        for p in ids:store.enqueue_paragraph_vector_backfill(p)
        store.mark_paragraph_vector_backfill_running(ids)
        before=[tuple(r) for r in store._conn.execute('SELECT * FROM paragraph_vector_backfill ORDER BY paragraph_hash')]
        store._conn.execute("CREATE TRIGGER fail_last BEFORE UPDATE ON paragraph_vector_backfill WHEN NEW.paragraph_hash='synthetic-0500' AND NEW.status='done' BEGIN SELECT RAISE(ABORT, 'synthetic'); END")
        store._conn.commit()
        with pytest.raises(sqlite3.IntegrityError):store.mark_paragraph_vector_backfill_done(ids)
        assert not store._conn.in_transaction
        assert [tuple(r) for r in store._conn.execute('SELECT * FROM paragraph_vector_backfill ORDER BY paragraph_hash')]==before
        # 后续提交不得顺带提交失败批次的前500项。
        store._conn.execute('DROP TRIGGER fail_last');store._conn.commit()
        store.close();store.connect()
        assert [tuple(r) for r in store._conn.execute('SELECT * FROM paragraph_vector_backfill ORDER BY paragraph_hash')]==before
        store.mark_paragraph_vector_backfill_done(ids)
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['done']==501
    finally:store.close()
