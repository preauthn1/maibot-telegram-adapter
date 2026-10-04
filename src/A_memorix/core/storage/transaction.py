from typing import Optional, Type

import sqlite3

from .sqlite_connection import ManagedSQLiteConnection


class ConnectionTransaction:
    """为外部注入的 SQLite 连接提供统一事务语义。"""

    def __init__(self, connection: sqlite3.Connection, *, immediate: bool = False) -> None:
        if not isinstance(connection, ManagedSQLiteConnection):
            raise TypeError("外部 SQLite 连接不支持受管事务；请注入 ManagedSQLiteConnection")
        self.connection = connection
        self.immediate = immediate
        self._savepoint_name: Optional[str] = None
        self._scope_depth: Optional[int] = None

    def __enter__(self) -> sqlite3.Connection:
        if self.connection.in_transaction:
            self._savepoint_name = f"a_memorix_override_{id(self)}"
            self.connection.execute(f"SAVEPOINT {self._savepoint_name}")
        else:
            self.connection.execute("BEGIN IMMEDIATE" if self.immediate else "BEGIN")
        # 与连接管理器一致：推迟业务方法的commit/rollback，交由外层边界处理。
        self._scope_depth = self.connection.begin_managed_scope()
        return self.connection

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: object,
    ) -> bool:
        assert self._scope_depth is not None
        rollback_requested = self.connection.end_managed_scope(self._scope_depth)
        self._scope_depth = None
        should_rollback = exc_type is not None or rollback_requested
        if self._savepoint_name is not None:
            if should_rollback:
                self.connection.execute(f"ROLLBACK TO SAVEPOINT {self._savepoint_name}")
            self.connection.execute(f"RELEASE SAVEPOINT {self._savepoint_name}")
            self._savepoint_name = None
        elif should_rollback:
            self.connection.force_rollback()
        else:
            try:
                self.connection.force_commit()
            except BaseException:
                # 提交失败同样需要回滚，而不仅是事务体内异常。
                self.connection.force_rollback()
                raise
        if rollback_requested and exc_type is None:
            raise RuntimeError("事务中的操作请求了回滚")
        return False
