from pymongo import MongoClient
from typing import Optional

class Database:
    _instance: Optional["Database"] = None
    
    def __init__(self, host: str, port: int, db_name: str):
        self.client = MongoClient(host, port)
        self.db = self.client[db_name]
        
    @classmethod
    def initialize(cls, host: str, port: int, db_name: str) -> "Database":
        if cls._instance is None:
            cls._instance = cls(host, port, db_name)
        return cls._instance
        
    @classmethod
    def get_instance(cls) -> "Database":
        if cls._instance is None:
            raise RuntimeError("Database not initialized")
        return cls._instance 