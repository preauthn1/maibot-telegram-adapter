"""历史恢复降级提示不能被后续阶段更新静默覆盖。"""
from unittest.mock import Mock
from src.maisaka import runtime as module


def test_restore_warning_survives_stage_updates_and_clears(monkeypatch):
    runtime=object.__new__(module.MaisakaHeartFlowChatting)
    runtime.session_id='synthetic'
    runtime.session_name='合成会话'
    runtime._agent_state='running'
    runtime._context_restore_failed=True
    sink=Mock()
    monkeypatch.setattr(module,'update_stage_status',sink)
    for stage in ('思考','回复','空闲'):
        runtime._update_stage_status(stage,'原阶段说明',round_text='回合1')
        data=sink.call_args.kwargs
        assert data['stage']==stage
        assert '原阶段说明' in data['detail']
        assert '近期历史恢复失败；当前上下文不完整' in data['detail']
        assert data['round_text']=='回合1'
    runtime._context_restore_failed=False
    runtime._update_stage_status('空闲','等待消息触发')
    assert sink.call_args.kwargs['detail']=='等待消息触发'
