"""真实SQLite部分恢复；单条恢复故障注入，图重建替身。"""
from types import SimpleNamespace
from unittest.mock import Mock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services import feedback_correction_service as module


def test_failed_restore_does_not_block_other_relations(tmp_path,monkeypatch):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        hashes=[store.add_relation(subject='合成甲',predicate='喜欢',obj=x,confidence=0.5) for x in ('合成乙','合成丙')]
        task=store.enqueue_feedback_task(query_tool_id='synthetic',session_id='synthetic',query_timestamp=100,due_at=200)
        assert task is not None
        before=store.get_relation_status_batch(hashes)
        store.mark_relations_inactive(hashes,reason='synthetic')
        original=store.restore_relation_status_from_snapshot
        def restore(key,snapshot):
            if key==hashes[0]:
                raise OSError('synthetic-private-restore-error')
            return original(key,snapshot)
        monkeypatch.setattr(store,'restore_relation_status_from_snapshot',restore)
        warning=Mock()
        monkeypatch.setattr(module.logger,'warning',warning)
        service=SimpleNamespace(metadata_store=store,_rebuild_graph_from_metadata=Mock(),_persist=Mock())
        result=module.MemoryFeedbackCorrectionService._restore_feedback_relations_from_snapshots(service,
            task_id=task['id'],query_tool_id='synthetic',relation_hashes=hashes,snapshots=before,reason='synthetic')
        assert result=={'restored_hashes':[hashes[1]],'failed_hashes':[hashes[0]]}
        warning.assert_called_once()
        assert 'OSError' in str(warning.call_args)
        assert 'synthetic-private-restore-error' not in str(warning.call_args)
        service._rebuild_graph_from_metadata.assert_called_once()
        service._persist.assert_called_once()
        store.close()
        store.connect()
        after=store.get_relation_status_batch(hashes)
        assert after[hashes[0]]['is_inactive'] is True
        assert after[hashes[1]]['is_inactive'] is False
        assert after[hashes[1]]['confidence']==before[hashes[1]]['confidence']
    finally:
        store.close()
