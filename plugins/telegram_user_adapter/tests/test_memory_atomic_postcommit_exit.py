"""真实子进程提交后立即退出；验证持久化待办，不代表worker崩溃重领。"""
import subprocess
import sys
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_process_exit_after_commit(tmp_path):
    store=MetadataStore(data_dir=tmp_path);store.connect();store.close()
    code='''import os,sys
from src.A_memorix.core.storage.metadata_store import MetadataStore
s=MetadataStore(data_dir=sys.argv[1]);s.connect()
s.ingest_relation_metadata_atomic(external_id='synthetic-committed',content='合成已提交记忆',source='chat:synthetic',source_type='chat_summary',queue_paragraph_vector=True,queue_relation_vectors=True,relations=[dict(subject='甲',predicate='喜欢',object='乙')])
os._exit(74)
'''
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
    assert result.returncode==74
    store.connect()
    try:
        ref=store.get_external_memory_ref('synthetic-committed')
        assert ref is not None
        p=ref['paragraph_hash']
        assert store.get_paragraph(p)['content']=='合成已提交记忆'
        h=store.compute_relation_hash('甲','喜欢','乙')
        before=store.get_relation(h)
        assert before['vector_state']=='pending'
        assert {r['hash'] for r in store.get_paragraph_relations(p)}=={h}
        tasks=store.fetch_paragraph_vector_backfill_batch()
        assert len(tasks)==1 and tasks[0]['paragraph_hash']==p and tasks[0]['status']=='pending'
        replay=store.ingest_relation_metadata_atomic(external_id='synthetic-committed',content='合成已提交记忆',source='chat:synthetic',source_type='chat_summary',queue_paragraph_vector=True,queue_relation_vectors=True,relations=[dict(subject='甲',predicate='喜欢',object='乙')])
        assert replay['reason']=='exists' and replay['stored_ids']==[]
        assert store.get_relation(h)==before
        assert store.fetch_paragraph_vector_backfill_batch()==tasks
        assert store._conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert store._conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    finally:store.close()
