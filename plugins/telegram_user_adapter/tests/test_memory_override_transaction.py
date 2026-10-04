"""真实临时SQLite：注入连接的事务不能被业务方法commit提前结束。"""
import asyncio
import sqlite3
import pytest
from src.A_memorix.core.storage.sqlite_connection import ManagedSQLiteConnection
from src.A_memorix.core.storage.transaction import ConnectionTransaction

@pytest.mark.parametrize('error',[OSError,asyncio.CancelledError])
def test_override_rollback_survives_internal_commit(tmp_path,error):
    path=tmp_path/'test.db'
    conn=sqlite3.connect(str(path),factory=ManagedSQLiteConnection)
    conn.execute('CREATE TABLE sample (value TEXT)')
    conn.commit()
    failure=error('synthetic')
    try:
        with pytest.raises(error) as caught:
            with ConnectionTransaction(conn):
                conn.execute("INSERT INTO sample VALUES ('temporary')")
                conn.commit()
                raise failure
        assert caught.value is failure
        assert conn._managed_transaction_depth==0
        assert not conn.in_transaction
    finally:
        conn.close()
    with sqlite3.connect(str(path)) as reopened:
        assert reopened.execute('SELECT count(*) FROM sample').fetchone()[0]==0


def test_override_nested_rollback_preserves_outer(tmp_path):
    conn=sqlite3.connect(str(tmp_path/'nested.db'),factory=ManagedSQLiteConnection)
    try:
        conn.execute('CREATE TABLE sample (value TEXT)')
        conn.commit()
        with ConnectionTransaction(conn):
            conn.execute("INSERT INTO sample VALUES ('outer')")
            with pytest.raises(OSError):
                with ConnectionTransaction(conn):
                    conn.execute("INSERT INTO sample VALUES ('inner')")
                    conn.commit()
                    raise OSError('synthetic')
            assert conn._managed_transaction_depth==1
            assert conn.execute('SELECT value FROM sample').fetchall()==[('outer',)]
        assert conn._managed_transaction_depth==0
        assert conn.execute('SELECT value FROM sample').fetchall()==[('outer',)]
    finally:
        conn.close()


def test_override_explicit_rollback_does_not_report_success(tmp_path):
    conn=sqlite3.connect(str(tmp_path/'rollback.db'),factory=ManagedSQLiteConnection)
    try:
        conn.execute('CREATE TABLE sample (value TEXT)')
        conn.commit()
        with pytest.raises(RuntimeError,match='事务中的操作请求了回滚'):
            with ConnectionTransaction(conn):
                conn.execute("INSERT INTO sample VALUES ('temporary')")
                conn.rollback()
        assert conn.execute('SELECT value FROM sample').fetchall()==[]
        assert conn._managed_transaction_depth==0
        with ConnectionTransaction(conn):
            conn.execute("INSERT INTO sample VALUES ('next')")
        assert conn.execute('SELECT value FROM sample').fetchall()==[('next',)]
    finally:
        conn.close()
