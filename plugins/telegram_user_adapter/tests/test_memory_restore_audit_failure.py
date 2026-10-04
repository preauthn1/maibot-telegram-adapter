"""真实SQLite批量恢复，审计故障注入；图重建为替身。"""
from types import SimpleNamespace
from unittest.mock import Mock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services import feedback_correction_service as module


def test_audit_failure_does_not_stop_remaining_restores(tmp_path, monkeypatch):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        hashes=[store.add_relation(subject='合成甲',predicate='喜欢',obj=obj,confidence=0.0) for obj in ('合成乙','合成丙')]
        task=store.enqueue_feedback_task(query_tool_id='synthetic',session_id='synthetic',query_timestamp=100,due_at=200)
        before=store.get_relation_status_batch(hashes)
        store.mark_relations_inactive(hashes,reason='synthetic')
        original=store.append_feedback_action_log
        def audit(**kwargs):
            if kwargs['target_hash']==hashes[0]:
                raise OSError('synthetic-private-detail')
            return original(**kwargs)
        monkeypatch.setattr(store,'append_feedback_action_log',audit)
        warning=Mock()
        monkeypatch.setattr(module.logger,'warning',warning)
        service=SimpleNamespace(metadata_store=store,_rebuild_graph_from_metadata=Mock(),_persist=Mock())
        result=module.MemoryFeedbackCorrectionService._restore_feedback_relations_from_snapshots(service,
            task_id=task['id'],query_tool_id='synthetic',relation_hashes=hashes,snapshots=before,reason='synthetic')
        assert result['restored_hashes']==hashes and result['failed_hashes']==[]
        warning.assert_called_once()
        assert 'OSError' in str(warning.call_args)
        assert 'synthetic-private-detail' not in str(warning.call_args)
        service._rebuild_graph_from_metadata.assert_called_once()
        service._persist.assert_called_once()
        store.close()
        store.connect()
        after=store.get_relation_status_batch(hashes)
        for key in hashes:
            assert after[key]['lifecycle_revision']>before[key]['lifecycle_revision']
            assert {k:v for k,v in after[key].items() if k!='lifecycle_revision'}=={k:v for k,v in before[key].items() if k!='lifecycle_revision'}
    finally:
        store.close()
