"""真实SQLite重复关系契约。"""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('conflict',[None,'score','metadata'])
def test_duplicate_relations(tmp_path,conflict):
    s=MetadataStore(data_dir=tmp_path);s.connect()
    try:
        a=dict(subject='甲',predicate='喜欢',object='乙',confidence=0.5,metadata={'source':'synthetic'})
        b=dict(a)
        if conflict=='score':b['confidence']=0.8
        if conflict=='metadata':b['metadata']={'source':'other'}
        kwargs=dict(external_id='synthetic-duplicates',content='合成重复',source='chat:synthetic',source_type='chat_summary',relations=[a,b])
        before=s._conn.total_changes
        if conflict:
            with pytest.raises(ValueError,match='conflicting_atomic_relation'):s.ingest_relation_metadata_atomic(**kwargs)
            assert s._conn.total_changes==before
        else:
            result=s.ingest_relation_metadata_atomic(**kwargs)
            assert len(result['stored_ids'])==2
        s.close();s.connect()
        assert s._conn.execute('SELECT count(*) FROM relations').fetchone()[0]==(0 if conflict else 1)
        if conflict:assert s.get_external_memory_ref('synthetic-duplicates') is None
    finally:s.close()
