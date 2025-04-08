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
from .reply_checker import ReplyChecker
from .pfc_utils import get_items_from_json
from src.individuality.individuality import Individuality
from .chat_states import NotificationHandler, Notification, NotificationType
import time
from dataclasses import dataclass, field
from .pfc import DecisionInfo, DecisionInfoType

logger = get_module_logger("action_planner")

class ActionPlanner:
    """行动规划器"""
    
    def __init__(self, stream_id: str):
        self.llm = LLM_request(
            model=global_config.llm_normal,
            temperature=0.7,
            max_tokens=1000,
            request_type="action_planning"
        )
        self.personality_info = Individuality.get_instance().get_prompt(type = "personality", x_person = 2, level = 2)
        self.name = global_config.BOT_NICKNAME
        self.chat_observer = ChatObserver.get_instance(stream_id)
        
    async def plan(
        self, 
        goal: str, 
        method: str, 
        reasoning: str,
        action_history: List[Dict[str, str]] = None,
        decision_info: DecisionInfoType = None  # Use DecisionInfoType here
    ) -> Tuple[str, str]:
        """规划下一步行动
        
        Args:
            goal: 对话目标
            method: 实现方法
            reasoning: 目标原因
            action_history: 行动历史记录
            decision_info: 决策信息
            
        Returns:
            Tuple[str, str]: (行动类型, 行动原因)
        """
        # 构建提示词
        logger.debug(f"开始规划行动：当前目标: {goal}")
        
        # 获取最近20条消息
        messages = self.chat_observer.get_message_history(limit=20)
        chat_history_text = ""
        for msg in messages:
            time_str = datetime.datetime.fromtimestamp(msg["time"]).strftime("%H:%M:%S")
            user_info = UserInfo.from_dict(msg.get("user_info", {}))
            sender = user_info.user_nickname or f"用户{user_info.user_id}"
            if sender == self.name:
                sender = "你说"
            chat_history_text += f"{time_str},{sender}:{msg.get('processed_plain_text', '')}\n"
            
        personality_text = f"你的名字是{self.name}，{self.personality_info}"
        
        # 构建action历史文本
        action_history_text = ""
        if action_history and action_history[-1]['action'] == "direct_reply":
            action_history_text = "你刚刚发言回复了对方"
            
        # 构建决策信息文本
        decision_info_text = ""
        if decision_info:
            decision_info_text = "当前对话状态：\n"
            if decision_info.is_cold_chat:
                decision_info_text += f"对话处于冷场状态，已持续{int(decision_info.cold_chat_duration)}秒\n"
            
            if decision_info.new_messages_count > 0:
                decision_info_text += f"有{decision_info.new_messages_count}条新消息未处理\n"
                
            user_response_time = decision_info.get_user_response_time()
            if user_response_time:
                decision_info_text += f"距离用户上次发言已过去{int(user_response_time)}秒\n"
                
            bot_response_time = decision_info.get_bot_response_time()
            if bot_response_time:
                decision_info_text += f"距离你上次发言已过去{int(bot_response_time)}秒\n"
                
            if decision_info.active_users:
                decision_info_text += f"当前活跃用户数: {len(decision_info.active_users)}\n"

        prompt = f"""{personality_text}。现在你在参与一场QQ聊天，请分析以下内容，根据信息决定下一步行动：

当前对话目标：{goal}
实现该对话目标的方式：{method}
产生该对话目标的原因：{reasoning}

{decision_info_text}
{action_history_text}

最近的对话记录：
{chat_history_text}

请你接下去想想要你要做什么，可以发言，可以等待，可以倾听，可以调取知识。注意不同行动类型的要求，不要重复发言：
行动类型：
fetch_knowledge: 需要调取知识，当需要专业知识或特定信息时选择
wait: 当你做出了发言,对方尚未回复时等待对方的回复
listening: 倾听对方发言，当你认为对方发言尚未结束时采用
direct_reply: 不符合上述情况，回复对方，注意不要过多或者重复发言
rethink_goal: 重新思考对话目标，当发现对话目标不合适时选择，会重新思考对话目标
judge_conversation: 判断对话是否结束，当发现对话目标已经达到或者希望停止对话时选择，会判断对话是否结束

请以JSON格式输出，包含以下字段：
1. action: 行动类型，注意你之前的行为
2. reason: 选择该行动的原因，注意你之前的行为（简要解释）

注意：请严格按照JSON格式输出，不要包含任何其他内容。"""

        logger.debug(f"发送到LLM的提示词: {prompt}")
        try:
            content, _ = await self.llm.generate_response_async(prompt)
            logger.debug(f"LLM原始返回内容: {content}")
            
            # 使用简化函数提取JSON内容
            success, result = get_items_from_json(
                content,
                "action", "reason",
                default_values={"action": "direct_reply", "reason": "默认原因"}
            )
            
            if not success:
                return "direct_reply", "JSON解析失败，选择直接回复"
            
            action = result["action"]
            reason = result["reason"]
            
            # 验证action类型
            if action not in ["direct_reply", "fetch_knowledge", "wait", "listening", "rethink_goal", "judge_conversation"]:
                logger.warning(f"未知的行动类型: {action}，默认使用listening")
                action = "listening"
                
            logger.info(f"规划的行动: {action}")
            logger.info(f"行动原因: {reason}")
            return action, reason
            
        except Exception as e:
            logger.error(f"规划行动时出错: {str(e)}")
            return "direct_reply", "发生错误，选择直接回复"