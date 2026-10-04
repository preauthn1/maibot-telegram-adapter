"""真实SQLite持久待办；不声称向量已经生成或恢复worker已运行。"""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore

@pytest.mark.parametrize('fail_ref',[False,True])
def test_pending_is_atomic_and_ready_preserved(tmp_path,monkeypatch,fail_ref):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    try:
        shared=store.add_relation('甲','喜欢','乙')
        store.set_relation_vector_state(shared,'ready')
        before=store.get_relation(shared)
        if fail_ref:
            def fail(**kw):raise OSError('synthetic')
            monkeypatch.setattr(store,'upsert_external_memory_ref',fail)
        kwargs=dict(external_id='synthetic-pending',content='合成向量待办',source='chat:synthetic',
            source_type='chat_summary',queue_relation_vectors=True,
            relations=[dict(subject='甲',predicate='喜欢',object='乙'),dict(subject='甲',predicate='喜欢',object='丙')])
        if fail_ref:
            with pytest.raises(OSError):store.ingest_relation_metadata_atomic(**kwargs)
        else:store.ingest_relation_metadata_atomic(**kwargs)
        store.close();store.connect()
        new=store.compute_relation_hash('甲','喜欢','丙')
        assert store.get_relation(shared)['vector_state']=='ready'
        if fail_ref:
            assert store.get_relation(shared)==before
            assert store.get_relation(new) is None
            assert store.get_external_memory_ref('synthetic-pending') is None
        else:
            assert store.get_relation(new)['vector_state']=='pending'
            assert store.get_external_memory_ref('synthetic-pending') is not None
    finally:store.close()
