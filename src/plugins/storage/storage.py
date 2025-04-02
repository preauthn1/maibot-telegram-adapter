from typing import Union, Optional

from ...common.database import db
from ..chat.message import MessageSending, MessageRecv
from ..chat.chat_stream import ChatStream
from src.common.logger import get_module_logger

logger = get_module_logger("message_storage")


class MessageStorage:
    async def store_message(self, message: Union[MessageSending, MessageRecv], chat_stream: ChatStream) -> None:
        """存储消息到数据库"""
        try:
            message_data = {
                "message_id": message.message_info.message_id,
                "time": message.message_info.time,
                "chat_id": chat_stream.stream_id,
                "chat_info": chat_stream.to_dict(),
                "user_info": message.message_info.user_info.to_dict(),
                "processed_plain_text": message.processed_plain_text,
                "detailed_plain_text": message.detailed_plain_text,
                "memorized_times": message.memorized_times,
            }
            db.messages.insert_one(message_data)
        except Exception:
            logger.exception("存储消息失败")

    async def get_last_message(self, chat_id: str, user_id: str) -> Optional[MessageRecv]:
        """获取指定聊天流和用户的最后一条消息
        
        Args:
            chat_id: 聊天流ID
            user_id: 用户ID
            
        Returns:
            Optional[MessageRecv]: 最后一条消息，如果没有找到则返回None
        """
        try:
            # 查找最后一条消息
            message_data = db.messages.find_one(
                {
                    "chat_id": chat_id,
                    "user_info.user_id": user_id
                },
                sort=[("time", -1)]  # 按时间降序排序
            )
            
            if not message_data:
                return None
                
            # 构建消息字典
            message_dict = {
                "message_info": {
                    "platform": message_data["chat_info"]["platform"],
                    "message_id": message_data["message_id"],
                    "time": message_data["time"],
                    "group_info": message_data["chat_info"].get("group_info"),
                    "user_info": message_data["user_info"]
                },
                "message_segment": {
                    "type": "text",
                    "data": message_data["processed_plain_text"]
                },
                "raw_message": message_data["processed_plain_text"]
            }
            
            # 创建并返回消息对象
            message = MessageRecv(message_dict)
            message.processed_plain_text = message_data["processed_plain_text"]
            message.detailed_plain_text = message_data["detailed_plain_text"]
            message.update_chat_stream(ChatStream.from_dict(message_data["chat_info"]))
            
            return message
            
        except Exception:
            logger.exception("获取最后一条消息失败")
            return None

    async def store_recalled_message(self, message_id: str, time: str, chat_stream: ChatStream) -> None:
        """存储撤回消息到数据库"""
        if "recalled_messages" not in db.list_collection_names():
            db.create_collection("recalled_messages")
        else:
            try:
                message_data = {
                    "message_id": message_id,
                    "time": time,
                    "stream_id": chat_stream.stream_id,
                }
                db.recalled_messages.insert_one(message_data)
            except Exception:
                logger.exception("存储撤回消息失败")

    async def remove_recalled_message(self, time: str) -> None:
        """删除撤回消息"""
        try:
            db.recalled_messages.delete_many({"time": {"$lt": time - 300}})
        except Exception:
            logger.exception("删除撤回消息失败")


# 如果需要其他存储相关的函数，可以在这里添加
