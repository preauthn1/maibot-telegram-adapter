from typing import Optional, Union

from ...common.database import Database
from .message_base import MessageBase
from .message import MessageSending, MessageRecv


class MessageStorage:
    def __init__(self):
        self.db = Database.get_instance()
        
    async def store_message(self, message: Union[MessageSending, MessageRecv], topic: Optional[str] = None) -> None:
        """存储消息到数据库"""
        try:
            message_data = {
                    "message_id": message.message_info.message_id,
                    "time": message.message_info.time,
                    "group_id": message.message_info.group_info.group_id,
                    "group_name": message.message_info.group_info.group_name,
                    "user_id": message.message_info.user_info.user_id,
                    "user_nickname": message.message_info.user_info.user_nickname,
                    "detailed_plain_text": message.detailed_plain_text,
                    "processed_plain_text": message.processed_plain_text,
                    "topic": topic,
                }
            self.db.db.messages.insert_one(message_data)
        except Exception as e:
            print(f"\033[1;31m[错误]\033[0m 存储消息失败: {e}") 

# 如果需要其他存储相关的函数，可以在这里添加 