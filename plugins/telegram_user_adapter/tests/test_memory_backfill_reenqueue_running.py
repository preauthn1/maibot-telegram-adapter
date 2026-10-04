"""真实SQLite：重复入队不得撤销执行中任务的领取状态。"""
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_reenqueue_preserves_running_claim(tmp_path):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        p=store.add_paragraph('合成重复入队')
        store.enqueue_paragraph_vector_backfill(p,error='synthetic-original')
        claimed=store.claim_paragraph_vector_backfill_batch(limit=1,max_retry=3)
        assert len(claimed)==1
        before=dict(store._conn.execute('SELECT * FROM paragraph_vector_backfill').fetchone())
        store.enqueue_paragraph_vector_backfill(p,error='synthetic-new')
        store.close();store.connect()
        assert dict(store._conn.execute('SELECT * FROM paragraph_vector_backfill').fetchone())==before
        assert store.claim_paragraph_vector_backfill_batch(limit=1,max_retry=3)==[]
        store.mark_paragraph_vector_backfill_done([p])
        assert store.get_paragraph_vector_backfill_status_counts()['done']==1
    finally:store.close()
