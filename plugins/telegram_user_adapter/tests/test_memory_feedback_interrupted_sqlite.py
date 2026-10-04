"""真实SQLite中断补偿；遗忘适配与图重建替身，无生产写入。"""
import asyncio
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services import feedback_correction_service as module

@pytest.mark.parametrize('cancelled',[False,True])
def test_interrupted_correction_restores_sqlite(tmp_path,monkeypatch,cancelled):
    monkeypatch.setattr(module,'feedback_cfg_auto_apply_threshold',lambda:0.8)
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        old=store.add_relation(subject='合成甲',predicate='喜欢',obj='合成乙',confidence=0.0)
        task=store.enqueue_feedback_task(query_tool_id='synthetic',session_id='synthetic',query_timestamp=100,due_at=200)
        assert task is not None
        before=store.get_relation_status_batch([old])[old]
        def forget(**kwargs):
            store.mark_relations_inactive(kwargs['hashes'],reason='synthetic-correction')
            assert store.get_relation_status_batch([old])[old]['is_inactive'] is True
            return {'success':True}
        error=asyncio.CancelledError() if cancelled else RuntimeError('synthetic interruption')
        service=SimpleNamespace(metadata_store=store,
            _resolve_feedback_relation_hashes=Mock(return_value=[old]),
            _query_relation_rows_by_hashes=Mock(return_value=[store.get_relation(old)]),
            _apply_v5_relation_action=forget,_ingest_feedback_relations=AsyncMock(side_effect=error),
            _rebuild_graph_from_metadata=Mock(),_persist=Mock())
        service._restore_feedback_relations_from_snapshots=MethodType(
            module.MemoryFeedbackCorrectionService._restore_feedback_relations_from_snapshots,service)
        with pytest.raises(type(error)) as caught:
            asyncio.run(module.MemoryFeedbackCorrectionService._apply_feedback_decision(service,
                task_id=task['id'],query_tool_id='synthetic',session_id='synthetic',hit_map={},
                decision={'decision':'correct','confidence':1,'target_hashes':[old],
                    'corrected_relations':[{'subject':'合成甲','predicate':'喜欢','object':'合成丙','confidence':1}]}))
        assert caught.value is error
        after=store.get_relation_status_batch([old])[old]
        assert after['lifecycle_revision']>before['lifecycle_revision']
        assert {k:v for k,v in after.items() if k!='lifecycle_revision'}=={k:v for k,v in before.items() if k!='lifecycle_revision'}
        service._rebuild_graph_from_metadata.assert_called_once()
        store.close()
        store.connect()
        assert store.get_relation_status_batch([old])[old]==after
    finally:
        store.close()
