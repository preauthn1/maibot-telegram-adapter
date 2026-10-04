"""真实候选查询验证会话范围、全局表达与人工审核过滤。"""
from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from sqlmodel import Session, create_engine
from src.chat.replyer import maisaka_expression_selector as module


@pytest.mark.parametrize('checked_only', [False, True])
def test_scoped_query_uses_real_sql(tmp_path, monkeypatch, checked_only):
    engine = create_engine('sqlite:///' + str(tmp_path / 'scope.db'))
    module.Expression.__table__.create(engine)
    with Session(engine) as session:
        for i, scope, checked, actor in [
            (1, 'current', True, module.ModifiedBy.USER),
            (2, 'other', True, module.ModifiedBy.USER),
            (3, None, True, module.ModifiedBy.USER),
            (4, 'current', False, None),
        ]:
            session.add(module.Expression(id=i, situation='合成倾诉情境', style='简短回应感受',
                content_list='[]', count=1, session_id=scope, checked=checked, modified_by=actor))
        session.commit()
    @contextmanager
    def db_session(**kwargs):
        assert kwargs == {'auto_commit': False}
        with Session(engine) as session:
            yield session
    monkeypatch.setattr(module, 'get_db_session', db_session)
    monkeypatch.setattr(module, 'global_config', SimpleNamespace(expression=SimpleNamespace(expression_checked_only=checked_only)))
    selector = object.__new__(module.MaisakaExpressionSelector)
    monkeypatch.setattr(selector, '_resolve_expression_group_scope', lambda sid: ([sid], False))
    results = selector._load_all_expression_candidates('current')
    assert {r['id'] for r in results} == ({1, 3} if checked_only else {1, 3, 4})
    with Session(engine) as session:
        assert session.get(module.Expression, 2).session_id == 'other'
    engine.dispose()
