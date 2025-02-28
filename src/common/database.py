from pymongo import MongoClient
from typing import Optional

class Database:
    _instance: Optional["Database"] = None
    
    def __init__(self, host: str, port: int, db_name: str, username: Optional[str] = None, password: Optional[str] = None, auth_source: Optional[str] = None):
        if username and password:
            # 如果有用户名和密码，使用认证连接
            # TODO: 复杂情况直接支持URI吧
            self.client = MongoClient(host, port, username=username, password=password, authSource=auth_source)
        else:
            # 否则使用无认证连接
            self.client = MongoClient(host, port)
        self.db = self.client[db_name]
        
    @classmethod
    def initialize(cls, host: str, port: int, db_name: str, username: Optional[str] = None, password: Optional[str] = None, auth_source: Optional[str] = None) -> "Database":
        if cls._instance is None:
            cls._instance = cls(host, port, db_name, username, password, auth_source)
        return cls._instance
        
    @classmethod
    def get_instance(cls) -> "Database":
        if cls._instance is None:
            raise RuntimeError("Database not initialized")
        return cls._instance