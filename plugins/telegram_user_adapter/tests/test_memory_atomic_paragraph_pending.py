"""真实SQLite段落回填待办的原子性及共享状态保护。"""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('prior',[None,'pending','running','done','failed'])
@pytest.mark.parametrize('fail_ref',[False,True])
def test_paragraph_pending_atomic(tmp_path,monkeypatch,prior,fail_ref):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        p=None;before=None
        if prior:
            p=store.add_paragraph('合成段落待办')
            store.enqueue_paragraph_vector_backfill(p)
            store._conn.execute('UPDATE paragraph_vector_backfill SET status=?,retry_count=3,last_error=? WHERE paragraph_hash=?',(prior,'synthetic',p))
            store._conn.commit()
            before=dict(store._conn.execute('SELECT * FROM paragraph_vector_backfill WHERE paragraph_hash=?',(p,)).fetchone())
        if fail_ref:
            def fail(**kw):raise OSError('synthetic')
            monkeypatch.setattr(store,'upsert_external_memory_ref',fail)
        kwargs=dict(external_id='synthetic-paragraph-queue',content='合成段落待办',source='chat:synthetic',
            source_type='chat_summary',queue_paragraph_vector=True,
            relations=[dict(subject='甲',predicate='喜欢',object='乙')])
        if fail_ref:
            with pytest.raises(OSError):store.ingest_relation_metadata_atomic(**kwargs)
        else:
            result=store.ingest_relation_metadata_atomic(**kwargs)
            p=result['stored_ids'][0]
        store.close();store.connect()
        tasks=[dict(r) for r in store._conn.execute('SELECT * FROM paragraph_vector_backfill')]
        if prior:
            assert tasks==[before]
        elif fail_ref:
            assert tasks==[]
            assert store._conn.execute('SELECT count(*) FROM paragraphs').fetchone()[0]==0
        else:
            assert len(tasks)==1 and tasks[0]['paragraph_hash']==p
            assert tasks[0]['status']=='pending' and tasks[0]['retry_count']==0
            assert store.fetch_paragraph_vector_backfill_batch()[0]['paragraph_hash']==p
        assert (store.get_external_memory_ref('synthetic-paragraph-queue') is not None) is (not fail_ref)
    finally:store.close()
