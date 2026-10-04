"""真实回执适配/应用编排/SQLite补偿；底层写入和图服务为替身。"""
import asyncio
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, AsyncMock
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.runtime.services import feedback_correction_service as module

@pytest.mark.parametrize('status',['false',1,None,False])
@pytest.mark.parametrize('audit_fails',[False,'ingest_correction','forget_relation'])
def test_failed_receipt_restores_persistent_old_relation(tmp_path,monkeypatch,status,audit_fails):
    monkeypatch.setattr(module,'feedback_cfg_auto_apply_threshold',lambda:0.8)
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        old=store.add_relation(subject='合成甲',predicate='喜欢',obj='合成乙',confidence=0.0)
        task=store.enqueue_feedback_task(query_tool_id='synthetic',session_id='synthetic',query_timestamp=100,due_at=200)
        assert task is not None
        before=store.get_relation_status_batch([old])[old]
        original_log=store.append_feedback_action_log
        def audit(**kwargs):
            if audit_fails and kwargs['action_type']==audit_fails:
                raise OSError('synthetic-private-audit-error')
            return original_log(**kwargs)
        monkeypatch.setattr(store,'append_feedback_action_log',audit)
        warning=Mock()
        monkeypatch.setattr(module.logger,'warning',warning)
        def forget(**kwargs):
            store.mark_relations_inactive(kwargs['hashes'],reason='synthetic-correction')
            assert store.get_relation_status_batch([old])[old]['is_inactive'] is True
            return {'success':True}
        service=SimpleNamespace(metadata_store=store,
            _resolve_feedback_relation_hashes=Mock(return_value=[old]),
            _query_relation_rows_by_hashes=Mock(return_value=[store.get_relation(old)]),
            _apply_v5_relation_action=forget,
            ingest_text=AsyncMock(return_value={'success':status,'stored_ids':['synthetic-paragraph','synthetic-new']}),
            _chat_source=lambda s:'synthetic:'+s,
            _rebuild_graph_from_metadata=Mock(),_persist=Mock())
        for method in ('_ingest_feedback_relations','_restore_feedback_relations_from_snapshots'):
            setattr(service,method,MethodType(getattr(module.MemoryFeedbackCorrectionService,method),service))
        result=asyncio.run(module.MemoryFeedbackCorrectionService._apply_feedback_decision(service,
            task_id=task['id'],query_tool_id='synthetic',session_id='synthetic',hit_map={},
            decision={'decision':'correct','confidence':1,'target_hashes':[old],
                'corrected_relations':[{'subject':'合成甲','predicate':'喜欢','object':'合成丙','confidence':1}]}))
        if audit_fails:
            warning.assert_called_once()
            assert 'OSError' in str(warning.call_args)
            assert 'synthetic-private-audit-error' not in str(warning.call_args)
        assert result['applied'] is False
        assert result['reason']=='correction_ingest_failed'
        assert result['restored_relation_hashes']==[old]
        assert result['restore_failed_hashes']==[]
        if type(status) is not bool:
            assert result['error']=='invalid_ingest_success_type'
        after=store.get_relation_status_batch([old])[old]
        assert after['lifecycle_revision']>before['lifecycle_revision']
        assert {k:v for k,v in after.items() if k!='lifecycle_revision'}=={k:v for k,v in before.items() if k!='lifecycle_revision'}
        service.ingest_text.assert_awaited_once()
        service._rebuild_graph_from_metadata.assert_called_once()
        store.close()
        store.connect()
        assert store.get_relation_status_batch([old])[old]==after
    finally:
        store.close()
