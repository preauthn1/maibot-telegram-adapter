"""同步元数据批次；真实SQLite，未接入运行时图/向量。"""
import asyncio
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('failure',[OSError,asyncio.CancelledError,None])
def test_atomic_batch(tmp_path,monkeypatch,failure):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        origin=store.add_paragraph('合成原来源')
        shared=store.add_relation('甲','喜欢','乙',confidence=0.9,source_paragraph=origin)
        before=store.get_relation(shared)
        original=store.add_relation
        calls=[]
        def add(**kw):
            calls.append(kw)
            if len(calls)==2 and failure:
                raise failure('synthetic')
            return original(**kw)
        monkeypatch.setattr(store,'add_relation',add)
        kwargs=dict(external_id='synthetic-atomic',content='合成批次',source='chat:synthetic',
            source_type='chat_summary',relations=[dict(subject='甲',predicate='喜欢',object='乙',confidence=0.5),
            dict(subject='甲',predicate='喜欢',object='丙',confidence=0.5)])
        if failure:
            with pytest.raises(failure):store.ingest_relation_metadata_atomic(**kwargs)
        else:
            result=store.ingest_relation_metadata_atomic(**kwargs)
            assert len(result['stored_ids'])==3
            count=len(calls)
            assert store.ingest_relation_metadata_atomic(**kwargs)['reason']=='exists'
            assert len(calls)==count
        store.close();store.connect()
        if failure:
            assert store.get_relation(shared)==before
            assert store.get_external_memory_ref('synthetic-atomic') is None
            assert store.get_relation(store.compute_relation_hash('甲','喜欢','丙')) is None
            assert store._conn.execute('SELECT count(*) FROM paragraphs').fetchone()[0]==1
            assert len(store.get_paragraph_relations(origin))==1
        else:
            ref=store.get_external_memory_ref('synthetic-atomic')
            assert len(store.get_paragraph_relations(ref['paragraph_hash']))==2
    finally:store.close()
