"""真实SQLite同内容段落复用失败：回滚元数据合并和复活副作用。"""
import asyncio
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('deleted',[False,True])
@pytest.mark.parametrize('failure',[OSError,asyncio.CancelledError])
def test_shared_paragraph_restored(tmp_path,monkeypatch,deleted,failure):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        p=store.add_paragraph('合成相同正文',source='chat:original',metadata={'original':True},
            knowledge_type='factual',time_meta={'event_time':1700000000.0})
        h=store.add_relation('甲','喜欢','乙',source_paragraph=p,confidence=0.9)
        store.upsert_external_memory_ref(external_id='synthetic-original',paragraph_hash=p,source_type='chat_summary')
        if deleted:
            store._conn.execute('UPDATE paragraphs SET is_deleted=1 WHERE hash=?',(p,));store._conn.commit()
        before_p=store.get_paragraph(p)
        before_h=store.get_relation(h)
        old_ref=store.get_external_memory_ref('synthetic-original')
        original=store.add_relation
        def add(**kw):
            if kw['obj']=='丙':raise failure('synthetic')
            return original(**kw)
        monkeypatch.setattr(store,'add_relation',add)
        with pytest.raises(failure):
            store.ingest_relation_metadata_atomic(external_id='synthetic-new',content='合成相同正文',
                source='chat:new',source_type='chat_summary',metadata={'new':True},
                relations=[dict(subject='甲',predicate='喜欢',object='乙',confidence=0.5),
                           dict(subject='甲',predicate='喜欢',object='丙',confidence=0.5)])
        store.close();store.connect()
        assert store.get_paragraph(p)==before_p
        assert store.get_relation(h)==before_h
        assert store.get_external_memory_ref('synthetic-original')==old_ref
        assert store.get_external_memory_ref('synthetic-new') is None
        assert {r['hash'] for r in store.get_paragraph_relations(p)}=={h}
        assert store.get_relation(store.compute_relation_hash('甲','喜欢','丙')) is None
    finally:store.close()
