import asyncio
import datetime
from typing import Dict, Any
from ..chat.message import Message
from .pfc import ConversationState, ChatObserver,GoalAnalyzer, Waiter, DirectMessageSender, PFCNotificationHandler
from src.common.logger import get_module_logger
from .action_planner import ActionPlanner
from .decision_info import DecisionInfo
from .reply_generator import ReplyGenerator
from ..chat.chat_stream import ChatStream
from ..message.message_base import UserInfo
from ..config.config import global_config
from src.plugins.chat.chat_stream import chat_manager
from .pfc_KnowledgeFetcher import KnowledgeFetcher
import time
import traceback

logger = get_module_logger("pfc_conversation")


class Conversation:
    """对话类，负责管理单个对话的状态和行为"""
    
    def __init__(self, stream_id: str):
        """初始化对话实例
        
        Args:
            stream_id: 聊天流ID
        """
        self.stream_id = stream_id
        self.state = ConversationState.INIT
        self.should_continue = False
        
        # 目标和规划        
        self.current_goal = "保持友好的对话"
        self.current_method = "以友好的态度回应"
        self.goal_reasoning = "确保对话顺利进行"
        
        # 知识缓存和行动历史
        self.knowledge_cache = {}
        self.action_history = []
        
        # 回复相关
        self.generated_reply = ""
    
    async def _initialize(self):
        """初始化实例，注册所有组件"""
        try:
            
            self.chat_observer = ChatObserver.get_instance(self.stream_id)
            self.action_planner = ActionPlanner(self.stream_id)
            self.goal_analyzer = GoalAnalyzer(self.stream_id)
            self.reply_generator = ReplyGenerator(self.stream_id)
            self.knowledge_fetcher = KnowledgeFetcher()
            self.waiter = Waiter(self.stream_id)
            self.direct_sender = DirectMessageSender()
            
            # 获取聊天流信息
            self.chat_stream = chat_manager.get_stream(self.stream_id)
            
            # 决策信息
            self.decision_info = DecisionInfo()
            self.decision_info.bot_id = global_config.BOT_QQ
            
            # 创建通知处理器
            self.notification_handler = PFCNotificationHandler(self)
        
        except Exception as e:
            logger.error(f"初始化对话实例：注册组件失败: {e}")
            logger.error(traceback.format_exc())
            raise
        
        try:
            start_time = time.time()
            self.chat_observer.start()  # 启动观察器
            logger.info(f"观察器启动完成，耗时: {time.time() - start_time:.2f}秒")
            
            await asyncio.sleep(1)  # 给观察器一些启动时间
            
            total_time = time.time() - start_time
            logger.info(f"实例初始化完成，总耗时: {total_time:.2f}秒")
            
            self.should_continue = True
            asyncio.create_task(self.start())
            
        except Exception as e:
            logger.error(f"初始化对话实例失败: {e}")
            logger.error(traceback.format_exc())
            raise
    
    async def start(self):
        """开始对话流程"""
        try:
            logger.info("对话系统启动")
            while self.should_continue:
                await self._do_a_step()
        except Exception as e:
            logger.error(f"启动对话系统失败: {e}")
            raise

    async def _do_a_step(self):
        """思考步"""
        # 获取最近的消息历史
        self.current_goal, self.current_method, self.goal_reasoning = await self.goal_analyzer.analyze_goal()
        
        self.chat_observer.trigger_update()  # 触发立即更新
        if not await self.chat_observer.wait_for_update():
            logger.warning("等待消息更新超时")
        
        # 使用决策信息来辅助行动规划
        action, reason = await self.action_planner.plan(
            self.current_goal,
            self.current_method,
            self.goal_reasoning,
            self.action_history,
            self.decision_info  # 传入决策信息
        )
        
        # 执行行动
        await self._handle_action(action, reason)
        
        # # 清理已处理的消息
        # self.decision_info.clear_unprocessed_messages()
            
    def _convert_to_message(self, msg_dict: Dict[str, Any]) -> Message:
        """将消息字典转换为Message对象"""
        try:
            chat_info = msg_dict.get("chat_info", {})
            chat_stream = ChatStream.from_dict(chat_info)
            user_info = UserInfo.from_dict(msg_dict.get("user_info", {}))
            
            return Message(
                message_id=msg_dict["message_id"],
                chat_stream=chat_stream,
                time=msg_dict["time"],
                user_info=user_info,
                processed_plain_text=msg_dict.get("processed_plain_text", ""),
                detailed_plain_text=msg_dict.get("detailed_plain_text", "")
            )
        except Exception as e:
            logger.warning(f"转换消息时出错: {e}")
            raise

    async def _handle_action(self, action: str, reason: str):
        """处理规划的行动"""
        logger.info(f"执行行动: {action}, 原因: {reason}")
        
        # 记录action历史
        self.action_history.append({
            "action": action,
            "reason": reason,
            "time": datetime.datetime.now().strftime("%H:%M:%S")
        })
        
        # 只保留最近的10条记录
        if len(self.action_history) > 10:
            self.action_history = self.action_history[-10:]
        
        if action == "direct_reply":
            self.state = ConversationState.GENERATING
            messages = self.chat_observer.get_message_history(limit=30)
            self.generated_reply = await self.reply_generator.generate(
                self.current_goal,
                self.current_method,
                [self._convert_to_message(msg) for msg in messages],
                self.knowledge_cache
            )
            
            # 检查回复是否合适
            is_suitable, reason, need_replan = await self.reply_generator.check_reply(
                self.generated_reply,
                self.current_goal
            )
            
            await self._send_reply()
            
        elif action == "fetch_knowledge":
            self.state = ConversationState.GENERATING
            messages = self.chat_observer.get_message_history(limit=30)
            knowledge, sources = await self.knowledge_fetcher.fetch(
                self.current_goal,
                [self._convert_to_message(msg) for msg in messages]
            )
            logger.info(f"获取到知识，来源: {sources}")
            
            if knowledge != "未找到相关知识":
                self.knowledge_cache[sources] = knowledge
        
        elif action == "rethink_goal":
            self.state = ConversationState.RETHINKING
            self.current_goal, self.current_method, self.goal_reasoning = await self.goal_analyzer.analyze_goal()
        
        elif action == "judge_conversation":
            self.state = ConversationState.JUDGING
            self.goal_achieved, self.stop_conversation, self.reason = await self.goal_analyzer.analyze_conversation(self.current_goal, self.goal_reasoning)
            
            # 如果当前目标达成但还有其他目标
            if self.goal_achieved and not self.stop_conversation:
                alternative_goals = await self.goal_analyzer.get_alternative_goals()
                if alternative_goals:
                    # 切换到下一个目标
                    self.current_goal, self.current_method, self.goal_reasoning = alternative_goals[0]
                    logger.info(f"当前目标已达成，切换到新目标: {self.current_goal}")
                    return
            
            if self.stop_conversation:
                await self._stop_conversation()
            
        elif action == "listening":
            self.state = ConversationState.LISTENING
            logger.info("倾听对方发言...")
            if await self.waiter.wait():  # 如果返回True表示超时
                await self._send_timeout_message()
                await self._stop_conversation()
            
        else:  # wait
            self.state = ConversationState.WAITING
            logger.info("等待更多信息...")
            if await self.waiter.wait():  # 如果返回True表示超时
                await self._send_timeout_message()
                await self._stop_conversation()

    async def _send_timeout_message(self):
        """发送超时结束消息"""
        try:
            messages = self.chat_observer.get_message_history(limit=1)
            if not messages:
                return
                
            latest_message = self._convert_to_message(messages[0])
            await self.direct_sender.send_message(
                chat_stream=self.chat_stream,
                content="抱歉，由于等待时间过长，我需要先去忙别的了。下次再聊吧~",
                reply_to_message=latest_message
            )
        except Exception as e:
            logger.error(f"发送超时消息失败: {str(e)}")

    async def _send_reply(self):
        """发送回复"""
        if not self.generated_reply:
            logger.warning("没有生成回复")
            return
            
        messages = self.chat_observer.get_message_history(limit=1)
        if not messages:
            logger.warning("没有最近的消息可以回复")
            return
            
        latest_message = self._convert_to_message(messages[0])
        try:
            await self.direct_sender.send_message(
                chat_stream=self.chat_stream,
                content=self.generated_reply,
                reply_to_message=latest_message
            )
            self.chat_observer.trigger_update()  # 触发立即更新
            if not await self.chat_observer.wait_for_update():
                logger.warning("等待消息更新超时")
            
            self.state = ConversationState.ANALYZING
        except Exception as e:
            logger.error(f"发送消息失败: {str(e)}")
            self.state = ConversationState.ANALYZING