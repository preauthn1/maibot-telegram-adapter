#Programmable Friendly Conversationalist
#Prefrontal cortex
import datetime
import asyncio
from typing import List, Optional, Tuple, TYPE_CHECKING
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
from .pfc_utils import get_items_from_json
from src.individuality.individuality import Individuality
from .chat_states import NotificationHandler, Notification, NotificationType
from .waiter import Waiter
from .message_sender import DirectMessageSender
from .notification_handler import PFCNotificationHandler
import time

if TYPE_CHECKING:
    from .conversation import Conversation

logger = get_module_logger("pfc")


class GoalAnalyzer:
    """对话目标分析器"""
    
    def __init__(self, stream_id: str):
        self.llm = LLM_request(
            model=global_config.llm_normal,
            temperature=0.7,
            max_tokens=1000,
            request_type="conversation_goal"
        )
        
        self.personality_info = Individuality.get_instance().get_prompt(type = "personality", x_person = 2, level = 2)
        self.name = global_config.BOT_NICKNAME
        self.nick_name = global_config.BOT_ALIAS_NAMES
        self.chat_observer = ChatObserver.get_instance(stream_id)
        
        # 多目标存储结构
        self.goals = []  # 存储多个目标
        self.max_goals = 3  # 同时保持的最大目标数量
        self.current_goal_and_reason = None

    async def analyze_goal(self) -> Tuple[str, str, str]:
        """分析对话历史并设定目标
        
        Args:
            chat_history: 聊天历史记录列表
            
        Returns:
            Tuple[str, str, str]: (目标, 方法, 原因)
        """
        max_retries = 3
        for retry in range(max_retries):
            try:
                # 构建提示词
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
                
                # 构建当前已有目标的文本
                existing_goals_text = ""
                if self.goals:
                    existing_goals_text = "当前已有的对话目标:\n"
                    for i, (goal, _, reason) in enumerate(self.goals):
                        existing_goals_text += f"{i+1}. 目标: {goal}, 原因: {reason}\n"
                    
                prompt = f"""{personality_text}。现在你在参与一场QQ聊天，请分析以下聊天记录，并根据你的性格特征确定多个明确的对话目标。
这些目标应该反映出对话的不同方面和意图。

{existing_goals_text}

聊天记录：
{chat_history_text}

请分析当前对话并确定最适合的对话目标。你可以：
1. 保持现有目标不变
2. 修改现有目标
3. 添加新目标
4. 删除不再相关的目标

请以JSON格式输出一个当前最主要的对话目标，包含以下字段：
1. goal: 对话目标（简短的一句话）
2. reasoning: 对话原因，为什么设定这个目标（简要解释）

输出格式示例：
{{
    "goal": "回答用户关于Python编程的具体问题",
    "reasoning": "用户提出了关于Python的技术问题，需要专业且准确的解答"
}}"""

                logger.debug(f"发送到LLM的提示词: {prompt}")
                content, _ = await self.llm.generate_response_async(prompt)
                logger.debug(f"LLM原始返回内容: {content}")
                
                # 使用简化函数提取JSON内容
                success, result = get_items_from_json(
                    content,
                    "goal", "reasoning",
                    required_types={"goal": str, "reasoning": str}
                )
                
                if not success:
                    logger.error(f"无法解析JSON，重试第{retry + 1}次")
                    continue
                    
                goal = result["goal"]
                reasoning = result["reasoning"]
                
                # 使用默认的方法
                method = "以友好的态度回应"
                
                # 更新目标列表
                await self._update_goals(goal, method, reasoning)
                
                # 返回当前最主要的目标
                if self.goals:
                    current_goal, current_method, current_reasoning = self.goals[0]
                    return current_goal, current_method, current_reasoning
                else:
                    return goal, method, reasoning
                
            except Exception as e:
                logger.error(f"分析对话目标时出错: {str(e)}，重试第{retry + 1}次")
                if retry == max_retries - 1:
                    return "保持友好的对话", "以友好的态度回应", "确保对话顺利进行"
                continue
        
        # 所有重试都失败后的默认返回
        return "保持友好的对话", "以友好的态度回应", "确保对话顺利进行"
    
    async def _update_goals(self, new_goal: str, method: str, reasoning: str):
        """更新目标列表
        
        Args:
            new_goal: 新的目标
            method: 实现目标的方法
            reasoning: 目标的原因
        """
        # 检查新目标是否与现有目标相似
        for i, (existing_goal, _, _) in enumerate(self.goals):
            if self._calculate_similarity(new_goal, existing_goal) > 0.7:  # 相似度阈值
                # 更新现有目标
                self.goals[i] = (new_goal, method, reasoning)
                # 将此目标移到列表前面（最主要的位置）
                self.goals.insert(0, self.goals.pop(i))
                return
        
        # 添加新目标到列表前面
        self.goals.insert(0, (new_goal, method, reasoning))
        
        # 限制目标数量
        if len(self.goals) > self.max_goals:
            self.goals.pop()  # 移除最老的目标
    
    def _calculate_similarity(self, goal1: str, goal2: str) -> float:
        """简单计算两个目标之间的相似度
        
        这里使用一个简单的实现，实际可以使用更复杂的文本相似度算法
        
        Args:
            goal1: 第一个目标
            goal2: 第二个目标
            
        Returns:
            float: 相似度得分 (0-1)
        """
        # 简单实现：检查重叠字数比例
        words1 = set(goal1)
        words2 = set(goal2)
        overlap = len(words1.intersection(words2))
        total = len(words1.union(words2))
        return overlap / total if total > 0 else 0
    
    async def get_all_goals(self) -> List[Tuple[str, str, str]]:
        """获取所有当前目标
        
        Returns:
            List[Tuple[str, str, str]]: 目标列表，每项为(目标, 方法, 原因)
        """
        return self.goals.copy()
    
    async def get_alternative_goals(self) -> List[Tuple[str, str, str]]:
        """获取除了当前主要目标外的其他备选目标
        
        Returns:
            List[Tuple[str, str, str]]: 备选目标列表
        """
        if len(self.goals) <= 1:
            return []
        return self.goals[1:].copy()

    async def analyze_conversation(self, goal, reasoning):
        messages = self.chat_observer.get_message_history()
        chat_history_text = ""
        for msg in messages:
            time_str = datetime.datetime.fromtimestamp(msg["time"]).strftime("%H:%M:%S")
            user_info = UserInfo.from_dict(msg.get("user_info", {}))
            sender = user_info.user_nickname or f"用户{user_info.user_id}"
            if sender == self.name:
                sender = "你说"
            chat_history_text += f"{time_str},{sender}:{msg.get('processed_plain_text', '')}\n"
            
        personality_text = f"你的名字是{self.name}，{self.personality_info}"
        
        prompt = f"""{personality_text}。现在你在参与一场QQ聊天，
        当前对话目标：{goal}
        产生该对话目标的原因：{reasoning}
        
        请分析以下聊天记录，并根据你的性格特征评估该目标是否已经达到，或者你是否希望停止该次对话。
        聊天记录：
        {chat_history_text}
        请以JSON格式输出，包含以下字段：
        1. goal_achieved: 对话目标是否已经达到（true/false）
        2. stop_conversation: 是否希望停止该次对话（true/false）
        3. reason: 为什么希望停止该次对话（简要解释）   

输出格式示例：
{{
    "goal_achieved": true,
    "stop_conversation": false,
    "reason": "虽然目标已达成，但对话仍然有继续的价值"
}}"""

        try:
            content, _ = await self.llm.generate_response_async(prompt)
            logger.debug(f"LLM原始返回内容: {content}")
            
            # 尝试解析JSON
            success, result = get_items_from_json(
                content,
                "goal_achieved", "stop_conversation", "reason",
                required_types={"goal_achieved": bool, "stop_conversation": bool, "reason": str}
            )
            
            if not success:
                logger.error("无法解析对话分析结果JSON")
                return False, False, "解析结果失败"
                
            goal_achieved = result["goal_achieved"]
            stop_conversation = result["stop_conversation"]
            reason = result["reason"]
            
            return goal_achieved, stop_conversation, reason
            
        except Exception as e:
            logger.error(f"分析对话状态时出错: {str(e)}")
            return False, False, f"分析出错: {str(e)}"


class Waiter:
    """快 速 等 待"""
    def __init__(self, stream_id: str):
        self.chat_observer = ChatObserver.get_instance(stream_id)
        self.personality_info = Individuality.get_instance().get_prompt(type = "personality", x_person = 2, level = 2)
        self.name = global_config.BOT_NICKNAME
        
    async def wait(self) -> bool:
        """等待
        
        Returns:
            bool: 是否超时（True表示超时）
        """
        # 使用当前时间作为等待开始时间
        wait_start_time = time.time()
        self.chat_observer.waiting_start_time = wait_start_time  # 设置等待开始时间
        
        while True:
            # 检查是否有新消息
            if self.chat_observer.new_message_after(wait_start_time):
                logger.info("等待结束，收到新消息")
                return False
                
            # 检查是否超时
            if time.time() - wait_start_time > 300:
                logger.info("等待超过300秒，结束对话")
                return True
                
            await asyncio.sleep(1)
            logger.info("等待中...")



class DirectMessageSender:
    """直接发送消息到平台的发送器"""
    
    def __init__(self):
        self.logger = get_module_logger("direct_sender")
        self.storage = MessageStorage()

    async def send_message(
        self,
        chat_stream: ChatStream,
        content: str,
        reply_to_message: Optional[Message] = None,
    ) -> None:
        """直接发送消息到平台
        
        Args:
            chat_stream: 聊天流
            content: 消息内容
            reply_to_message: 要回复的消息
        """
        # 构建消息对象
        message_segment = Seg(type="text", data=content)
        bot_user_info = UserInfo(
            user_id=global_config.BOT_QQ,
            user_nickname=global_config.BOT_NICKNAME,
            platform=chat_stream.platform,
        )
        
        message = MessageSending(
            message_id=f"dm{round(time.time(), 2)}",
            chat_stream=chat_stream,
            bot_user_info=bot_user_info,
            sender_info=reply_to_message.message_info.user_info if reply_to_message else None,
            message_segment=message_segment,
            reply=reply_to_message,
            is_head=True,
            is_emoji=False,
            thinking_start_time=time.time(),
        )

        # 处理消息
        await message.process()

        # 发送消息
        try:
            message_json = message.to_dict()
            end_point = global_config.api_urls.get(chat_stream.platform, None)
            
            if not end_point:
                raise ValueError(f"未找到平台：{chat_stream.platform} 的url配置")
                
            await global_api.send_message_REST(end_point, message_json)
            
            # 存储消息
            await self.storage.store_message(message, message.chat_stream)
            
            self.logger.info(f"直接发送消息成功: {content[:30]}...")
            
        except Exception as e:
            self.logger.error(f"直接发送消息失败: {str(e)}")
            raise

