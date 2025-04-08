#Programmable Friendly Conversationalist
#Prefrontal cortex
import datetime
import asyncio
from typing import List, Optional, Dict, Any, Tuple, Literal, Set
from enum import Enum
from src.common.logger import get_module_logger
from ..chat.chat_stream import ChatStream
from ..message.message_base import UserInfo, Seg
from ..chat.message import Message
from ..models.utils_model import LLM_request
from ..config.config import global_config
from src.plugins.chat.message import MessageSending
from ..message.api import global_api
from ..storage.storage import MessageStorage
from .chat_observer import ChatObserver
from .reply_generator import ReplyGenerator
from .pfc_utils import get_items_from_json
from src.individuality.individuality import Individuality
from .chat_states import NotificationHandler, Notification, NotificationType
import time
from dataclasses import dataclass, field
from .conversation import Conversation


@dataclass
class DecisionInfo:
    """决策信息类，用于收集和管理来自chat_observer的通知信息"""
    
    # 消息相关
    last_message_time: Optional[float] = None
    last_message_content: Optional[str] = None
    last_message_sender: Optional[str] = None
    new_messages_count: int = 0
    unprocessed_messages: List[Dict[str, Any]] = field(default_factory=list)
    
    # 对话状态
    is_cold_chat: bool = False
    cold_chat_duration: float = 0.0
    last_bot_speak_time: Optional[float] = None
    last_user_speak_time: Optional[float] = None
    
    # 对话参与者
    active_users: Set[str] = field(default_factory=set)
    bot_id: str = field(default="")
    
    def update_from_message(self, message: Dict[str, Any]):
        """从消息更新信息
        
        Args:
            message: 消息数据
        """
        self.last_message_time = message["time"]
        self.last_message_content = message.get("processed_plain_text", "")
        
        user_info = UserInfo.from_dict(message.get("user_info", {}))
        self.last_message_sender = user_info.user_id
        
        if user_info.user_id == self.bot_id:
            self.last_bot_speak_time = message["time"]
        else:
            self.last_user_speak_time = message["time"]
            self.active_users.add(user_info.user_id)
        
        self.new_messages_count += 1
        self.unprocessed_messages.append(message)
    
    def update_cold_chat_status(self, is_cold: bool, current_time: float):
        """更新冷场状态
        
        Args:
            is_cold: 是否冷场
            current_time: 当前时间
        """
        self.is_cold_chat = is_cold
        if is_cold and self.last_message_time:
            self.cold_chat_duration = current_time - self.last_message_time
    
    def get_active_duration(self) -> float:
        """获取当前活跃时长
        
        Returns:
            float: 最后一条消息到现在的时长（秒）
        """
        if not self.last_message_time:
            return 0.0
        return time.time() - self.last_message_time
    
    def get_user_response_time(self) -> Optional[float]:
        """获取用户响应时间
        
        Returns:
            Optional[float]: 用户最后发言到现在的时长（秒），如果没有用户发言则返回None
        """
        if not self.last_user_speak_time:
            return None
        return time.time() - self.last_user_speak_time
    
    def get_bot_response_time(self) -> Optional[float]:
        """获取机器人响应时间
        
        Returns:
            Optional[float]: 机器人最后发言到现在的时长（秒），如果没有机器人发言则返回None
        """
        if not self.last_bot_speak_time:
            return None
        return time.time() - self.last_bot_speak_time
    
    def clear_unprocessed_messages(self):
        """清空未处理消息列表"""
        self.unprocessed_messages.clear()
        self.new_messages_count = 0


# Forward reference for type hints
DecisionInfoType = DecisionInfo