"""子进程os._exit不跑清理，真实SQLite未提交事务崩溃回滚。"""
import subprocess
import sys
from src.A_memorix.core.storage.metadata_store import MetadataStore


def test_process_exit_before_atomic_commit(tmp_path):
    store=MetadataStore(data_dir=tmp_path);store.connect()
    origin=store.add_paragraph('合成崩溃原来源')
    shared=store.add_relation('甲','喜欢','乙',source_paragraph=origin,confidence=0.9)
    before=store.get_relation(shared)
    store.close()
    code='''import os,sys
from src.A_memorix.core.storage.metadata_store import MetadataStore
store=MetadataStore(data_dir=sys.argv[1]);store.connect()
original=store.add_relation
def crash(**kw):
    result=original(**kw)
    os._exit(73)
store.add_relation=crash
store.ingest_relation_metadata_atomic(external_id='synthetic-crash',content='合成崩溃新段落',source='chat:synthetic',source_type='chat_summary',queue_paragraph_vector=True,queue_relation_vectors=True,relations=[dict(subject='甲',predicate='喜欢',object='乙'),dict(subject='甲',predicate='喜欢',object='丙')])
'''
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
    assert result.returncode==73
    store.connect()
    try:
        assert store.get_relation(shared)==before
        assert store.get_external_memory_ref('synthetic-crash') is None
        assert store._conn.execute('SELECT count(*) FROM paragraphs').fetchone()[0]==1
        assert {r['hash'] for r in store.get_paragraph_relations(origin)}=={shared}
        assert store.get_relation(store.compute_relation_hash('甲','喜欢','丙')) is None
        assert store._conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert store._conn.execute('PRAGMA foreign_key_check').fetchall()==[]
    finally:store.close()
