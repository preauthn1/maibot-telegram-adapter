"""真实线程/SQLite并发，固定同步点而非依赖sleep；无生产调用。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('round_index', range(3))
def test_same_external_id_concurrent(tmp_path,round_index):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        origin=store.add_paragraph('合成共享来源')
        shared=store.add_relation('甲','喜欢','乙',source_paragraph=origin,confidence=0.9)
        before=store.get_relation(shared)
        barrier=Barrier(2,timeout=10)
        kwargs=dict(external_id='synthetic-concurrent',content='合成并发提交',source='chat:synthetic',
            source_type='chat_summary',relations=[dict(subject='甲',predicate='喜欢',object='乙',confidence=0.5),
            dict(subject='甲',predicate='喜欢',object='丙',confidence=0.5)])
        def submit():
            barrier.wait()
            return store.ingest_relation_metadata_atomic(**kwargs)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(submit) for _ in range(2)]
            results=[f.result(timeout=30) for f in futures]
        written=[r for r in results if r['stored_ids']]
        skipped=[r for r in results if r.get('reason')=='exists']
        assert len(written)==len(skipped)==1
        paragraph=written[0]['stored_ids'][0]
        assert skipped[0]['skipped_ids']==[paragraph]
        store.close();store.connect()
        after=store.get_relation(shared)
        assert after['reinforcement_count']==before['reinforcement_count']+1
        assert after['confidence']==before['confidence']
        assert after['source_paragraph']==origin
        assert len(store.get_paragraph_relations(paragraph))==2
        assert len(store.get_paragraph_relations(origin))==1
        assert store.get_external_memory_ref('synthetic-concurrent')['paragraph_hash']==paragraph
        assert store._conn.execute('SELECT count(*) FROM paragraphs').fetchone()[0]==2
        assert store._conn.execute('SELECT count(*) FROM external_memory_refs').fetchone()[0]==1
    finally:
        store.close()
