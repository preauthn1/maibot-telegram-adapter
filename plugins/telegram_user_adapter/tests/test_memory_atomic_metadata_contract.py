"""原子提交的时间与来源契约：真实临时SQLite回读，无网络。"""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('fail_ref',[False,True])
def test_atomic_metadata_contract(tmp_path,monkeypatch,fail_ref):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        kwargs=dict(external_id='synthetic-contract',content='合成事件正文',source='chat:synthetic',
            source_type='chat_summary',knowledge_type='factual',
            time_meta={'event_time':1700000000.0,'event_time_start':1699999900.0,'event_time_end':1700000100.0,'time_confidence':0.75},
            metadata={'source_marker':'synthetic'},external_metadata={'chat_id':'synthetic','person_ids':['synthetic-person']},
            relations=[{'subject':'甲','predicate':'喜欢','object':'乙','confidence':0}])
        if fail_ref:
            def fail(**kw): raise OSError('synthetic ref failure')
            monkeypatch.setattr(store,'upsert_external_memory_ref',fail)
            with pytest.raises(OSError):store.ingest_relation_metadata_atomic(**kwargs)
        else:
            result=store.ingest_relation_metadata_atomic(**kwargs)
        store.close();store.connect()
        if fail_ref:
            assert store._conn.execute('SELECT count(*) FROM paragraphs').fetchone()[0]==0
            assert store._conn.execute('SELECT count(*) FROM relations').fetchone()[0]==0
            assert store.get_external_memory_ref('synthetic-contract') is None
        else:
            p=store.get_paragraph(result['stored_ids'][0])
            assert p['knowledge_type']=='factual'
            for key,value in kwargs['time_meta'].items():assert p[key]==value
            assert p['metadata']==kwargs['metadata']
            ref=store.get_external_memory_ref('synthetic-contract')
            assert ref['source_type']=='chat_summary'
            assert ref['metadata']==kwargs['external_metadata']
            assert store.get_relation(result['stored_ids'][1])['confidence']==0
    finally:store.close()
