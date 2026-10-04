"""真实事务管理器与 SQLite：提交前故障必须回滚且保留表达结果。"""
from datetime import datetime
from unittest.mock import Mock
from sqlmodel import Session, create_engine
from src.common.database import database as db
from src.chat.replyer import maisaka_expression_selector as module


def test_commit_failure_rolls_back_and_preserves_selection(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'commit-failure.db'))
    module.Expression.__table__.create(engine)
    old = datetime(2020, 1, 1)
    with Session(engine) as session:
        session.add(module.Expression(id=2, situation='倾诉', style='先回应感受',
            content_list='[]', count=7, last_active_time=old, session_id='synthetic'))
        session.commit()
    session = Session(engine)
    original_execute = session.execute
    executed = []
    def execute(*args, **kwargs):
        result = original_execute(*args, **kwargs)
        executed.append(True)
        return result
    monkeypatch.setattr(session, 'execute', execute)
    rollback = Mock(wraps=session.rollback)
    close = Mock(wraps=session.close)
    monkeypatch.setattr(session, 'rollback', rollback)
    monkeypatch.setattr(session, 'close', close)
    monkeypatch.setattr(session, 'commit', Mock(side_effect=OSError('PRIVATE_COMMIT_DETAIL')))
    monkeypatch.setattr(db, 'initialize_database', lambda: None)
    monkeypatch.setattr(db, 'SessionLocal', lambda: session)
    monkeypatch.setattr(module, 'get_db_session', db.get_db_session)
    log = Mock()
    monkeypatch.setattr(module, 'logger', log)
    selector = object.__new__(module.MaisakaExpressionSelector)
    try:
        result = selector._build_selection_result_from_ids(
            candidates=[{'id':2, 'situation':'倾诉', 'style':'先回应感受', 'count':7}], selected_ids=[2])
        assert executed == [True]
        rollback.assert_called_once_with()
        close.assert_called_once_with()
        assert result.selected_expression_ids == [2]
        assert '先回应感受' in result.expression_habits
        with Session(engine) as fresh:
            row = fresh.get(module.Expression, 2)
            assert row.last_active_time == old and row.count == 7
        log.warning.assert_called_once()
        assert 'PRIVATE_COMMIT_DETAIL' not in str(log.mock_calls)
    finally:
        engine.dispose()
