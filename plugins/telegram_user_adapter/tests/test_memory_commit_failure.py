"""真实SQLite延迟外键：提交失败后连接必须回到干净状态。"""
import sqlite3
import pytest
from src.A_memorix.core.storage.sqlite_connection import SQLiteConnectionManager
from src.A_memorix.core.storage.transaction import ConnectionTransaction

@pytest.mark.parametrize('override',[False,True])
def test_deferred_constraint_commit_failure(tmp_path,override):
    manager=SQLiteConnectionManager(tmp_path/'commit.db')
    conn=manager.connection()
    scope=lambda: ConnectionTransaction(conn) if override else manager.transaction()
    try:
        conn.execute('CREATE TABLE parent (id INTEGER PRIMARY KEY)')
        conn.execute('CREATE TABLE child (pid INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)')
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            with scope():
                conn.execute('INSERT INTO child VALUES (17)')
        assert not conn.in_transaction
        assert conn._managed_transaction_depth==0
        assert conn.execute('SELECT * FROM child').fetchall()==[]
        with scope():
            conn.execute('INSERT INTO parent VALUES (17)')
        manager.close_current()
        reopened=manager.connection()
        assert reopened.execute('SELECT count(*) FROM child').fetchone()[0]==0
        assert reopened.execute('SELECT count(*) FROM parent').fetchone()[0]==1
    finally:
        manager.close_all()
