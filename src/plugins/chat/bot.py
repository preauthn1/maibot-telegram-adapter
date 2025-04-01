import re
import time
from random import random

from ..memory_system.Hippocampus import HippocampusManager
from ..moods.moods import MoodManager  # 导入情绪管理器
from ..config.config import global_config
from .emoji_manager import emoji_manager  # 导入表情包管理器
from ..chat_module.reasoning_chat.reasoning_generator import ResponseGenerator
from .message import MessageSending, MessageRecv, MessageThinking, MessageSet

from .chat_stream import chat_manager

from .message_sender import message_manager  # 导入新的消息管理器
from ..relationship.relationship_manager import relationship_manager
from ..storage.storage import MessageStorage  # 修改导入路径
from .utils import is_mentioned_bot_in_message, get_recent_group_detailed_plain_text
from .utils_image import image_path_to_base64
from ..willing.willing_manager import willing_manager  # 导入意愿管理器
from ..message import UserInfo, Seg

from src.heart_flow.heartflow import heartflow
from src.common.logger import get_module_logger, CHAT_STYLE_CONFIG, LogConfig
from ..chat_module.think_flow_chat.think_flow_chat import ThinkFlowChat
from ..chat_module.reasoning_chat.reasoning_chat import ReasoningChat

# 定义日志配置
chat_config = LogConfig(
    # 使用消息发送专用样式
    console_format=CHAT_STYLE_CONFIG["console_format"],
    file_format=CHAT_STYLE_CONFIG["file_format"],
)

# 配置主程序日志格式
logger = get_module_logger("chat_bot", config=chat_config)


class ChatBot:
    def __init__(self):
        self.storage = MessageStorage()
        self.gpt = ResponseGenerator()
        self.bot = None  # bot 实例引用
        self._started = False
        self.mood_manager = MoodManager.get_instance()  # 获取情绪管理器单例
        self.mood_manager.start_mood_update()  # 启动情绪更新
        self.think_flow_chat = ThinkFlowChat()
        self.reasoning_chat = ReasoningChat()

    async def _ensure_started(self):
        """确保所有任务已启动"""
        if not self._started:
            self._started = True

    async def message_process(self, message_data: str) -> None:
        """处理转化后的统一格式消息
        根据global_config.response_mode选择不同的回复模式：
        1. heart_flow模式：使用思维流系统进行回复
           - 包含思维流状态管理
           - 在回复前进行观察和状态更新
           - 回复后更新思维流状态
        
        2. reasoning模式：使用推理系统进行回复
           - 直接使用意愿管理器计算回复概率
           - 没有思维流相关的状态管理
           - 更简单直接的回复逻辑
        
        两种模式都包含：
        - 消息过滤
        - 记忆激活
        - 意愿计算
        - 消息生成和发送
        - 表情包处理
        - 性能计时
        """

        if global_config.response_mode == "heart_flow":
            await self.think_flow_chat.process_message(message_data)
        elif global_config.response_mode == "reasoning":
            await self.reasoning_chat.process_message(message_data)
        else:
            logger.error(f"未知的回复模式，请检查配置文件！！: {global_config.response_mode}")


# 创建全局ChatBot实例
chat_bot = ChatBot()
