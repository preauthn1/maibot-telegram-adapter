"""真实双线程SQLite领取，非租约或硬退出恢复测试。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_claims_are_disjoint(tmp_path):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        expected=set()
        for i in range(4):
            p=store.add_paragraph('合成领取'+str(i));expected.add(p)
            store.enqueue_paragraph_vector_backfill(p)
        barrier=Barrier(2,timeout=10)
        def claim():
            barrier.wait()
            return store.claim_paragraph_vector_backfill_batch(limit=3,max_retry=0)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(claim) for _ in range(2)]
            results=[f.result(timeout=30) for f in futures]
        groups=[{r['paragraph_hash'] for r in rows} for rows in results]
        assert not groups[0]&groups[1]
        assert groups[0]|groups[1]==expected
        store.close();store.connect()
        assert store.get_paragraph_vector_backfill_status_counts()['running']==4
        assert store.claim_paragraph_vector_backfill_batch(limit=4,max_retry=0)==[]
    finally:store.close()
