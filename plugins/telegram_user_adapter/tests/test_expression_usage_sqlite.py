"""真实 SQL 更新在临时 SQLite 提交后只改变选中行。"""
from contextlib import contextmanager
from datetime import datetime
from sqlmodel import Session, create_engine
from src.chat.replyer import maisaka_expression_selector as module


def test_usage_update_persists_only_selected_row(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'usage.db'))
    module.Expression.__table__.create(engine)
    old = datetime(2020, 1, 1)
    with Session(engine) as session:
        for i in (1, 2):
            session.add(module.Expression(id=i, situation='合成情境', style='合成表达',
                content_list='[]', count=7, last_active_time=old, session_id=f'synthetic-{i}'))
        session.commit()
    @contextmanager
    def db_session():
        with Session(engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
    monkeypatch.setattr(module, 'get_db_session', db_session)
    selector = object.__new__(module.MaisakaExpressionSelector)
    selector._update_last_active_time([1])
    # 新会话回读，避免仅检查 ORM 内存状态。
    with Session(engine) as session:
        first = session.get(module.Expression, 1)
        second = session.get(module.Expression, 2)
        assert first.last_active_time > old
        assert second.last_active_time == old
        assert first.count == second.count == 7
    engine.dispose()
