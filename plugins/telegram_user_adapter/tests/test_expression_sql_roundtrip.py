"""临时数据库真实查询、采样、选择装配和提交回读；模型与插件隔离。"""
import asyncio
import json
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
import pytest
from sqlmodel import Session, create_engine
from src.chat.replyer import maisaka_expression_selector as module


@pytest.mark.parametrize('abort', [False, True])
def test_sql_selection_roundtrip(tmp_path, monkeypatch, abort):
    engine = create_engine('sqlite:///' + str(tmp_path / 'roundtrip.db'))
    module.Expression.__table__.create(engine)
    old = datetime(2020, 1, 1)
    with Session(engine) as session:
        for i in range(1, 14):
            session.add(module.Expression(id=i, situation=f'合成情境{i}', style=f'合成表达{i}',
                content_list='[]', count=2, last_active_time=old,
                session_id='current' if i <= 12 else 'other'))
        session.commit()
    @contextmanager
    def db_session(auto_commit=True):
        with Session(engine) as session:
            try:
                yield session
                if auto_commit:
                    session.commit()
            except Exception:
                session.rollback()
                raise
    monkeypatch.setattr(module, 'get_db_session', db_session)
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(expression=SimpleNamespace(
        expression_checked_only=False, expression_selection_mode='legacy', expression_groups=[])))
    selector = object.__new__(module.MaisakaExpressionSelector)
    monkeypatch.setattr(selector, '_can_use_expressions', lambda sid: True)
    observed = {}
    async def hook(name, **kwargs):
        if name == 'expression.select.before_select':
            observed['ids'] = [c['id'] for c in kwargs['candidates']]
        return SimpleNamespace(kwargs=kwargs, aborted=abort and name.endswith('after_selection'))
    monkeypatch.setattr(selector, '_get_runtime_manager', lambda: SimpleNamespace(invoke_hook=hook))
    async def runner(prompt):
        assert len(observed['ids']) == len(set(observed['ids'])) == 10
        assert 13 not in observed['ids']
        observed['chosen'] = observed['ids'][0]
        return json.dumps({'selected_ids': [observed['chosen']]})
    result = asyncio.run(selector.select_for_reply(session_id='current', chat_history=[],
        reply_message=None, reply_reason='合成测试', sub_agent_runner=runner))
    chosen = observed['chosen']
    assert result.selected_expression_ids == ([] if abort else [chosen])
    assert bool(result.expression_habits) is (not abort)
    with Session(engine) as session:
        for i in range(1, 14):
            row = session.get(module.Expression, i)
            assert row is not None
            assert (row.last_active_time > old) is (not abort and i == chosen)
            assert row.count == 2
    engine.dispose()
