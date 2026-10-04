"""真实SQLite领取失败回滚；同步注入取消，不模拟进程硬退出。"""
import asyncio
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('error_type',[OSError,asyncio.CancelledError])
def test_claim_failure_rolls_back(tmp_path,monkeypatch,error_type):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        ids=[store.add_paragraph('合成领取回滚'+str(i)) for i in range(2)]
        for p in ids:store.enqueue_paragraph_vector_backfill(p)
        before=[dict(r) for r in store._conn.execute('SELECT * FROM paragraph_vector_backfill ORDER BY paragraph_hash')]
        mark=store.mark_paragraph_vector_backfill_running
        error=error_type('synthetic')
        def interrupted(hashes):
            mark(hashes)
            raise error
        monkeypatch.setattr(store,'mark_paragraph_vector_backfill_running',interrupted)
        with pytest.raises(error_type) as caught:
            store.claim_paragraph_vector_backfill_batch(limit=2,max_retry=0)
        assert caught.value is error
        assert not store._conn.in_transaction
        store.close();store.connect()
        after=[dict(r) for r in store._conn.execute('SELECT * FROM paragraph_vector_backfill ORDER BY paragraph_hash')]
        assert after==before
        monkeypatch.setattr(store,'mark_paragraph_vector_backfill_running',mark)
        claimed=store.claim_paragraph_vector_backfill_batch(limit=2,max_retry=0)
        assert {r['paragraph_hash'] for r in claimed}==set(ids)
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['running']==2
    finally:store.close()
