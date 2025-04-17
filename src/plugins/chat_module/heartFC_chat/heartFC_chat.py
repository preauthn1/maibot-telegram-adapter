import time
from random import random
import traceback
from typing import List, Optional
import asyncio
from ...moods.moods import MoodManager
from ....config.config import global_config
from ...chat.emoji_manager import emoji_manager
from .heartFC__generator import ResponseGenerator
from ...chat.message import MessageSending, MessageRecv, MessageThinking, MessageSet
from .messagesender import MessageManager
from ...chat.utils_image import image_path_to_base64
from ...message import UserInfo, Seg
from src.heart_flow.heartflow import heartflow
from src.common.logger import get_module_logger, CHAT_STYLE_CONFIG, LogConfig
from ...person_info.relationship_manager import relationship_manager
from src.plugins.respon_info_catcher.info_catcher import info_catcher_manager
from ...utils.timer_calculater import Timer
from src.do_tool.tool_use import ToolUser
from .interest import InterestManager, InterestChatting

# 定义日志配置
chat_config = LogConfig(
    console_format=CHAT_STYLE_CONFIG["console_format"],
    file_format=CHAT_STYLE_CONFIG["file_format"],
)

logger = get_module_logger("heartFC_chat", config=chat_config)

# 新增常量
INTEREST_LEVEL_REPLY_THRESHOLD = 4.0
INTEREST_MONITOR_INTERVAL_SECONDS = 1

class HeartFC_Chat:
    def __init__(self):
        self.gpt = ResponseGenerator()
        self.mood_manager = MoodManager.get_instance()
        self.mood_manager.start_mood_update()
        self.tool_user = ToolUser()
        self.interest_manager = InterestManager()
        self._interest_monitor_task: Optional[asyncio.Task] = None

    async def start(self):
        """Starts asynchronous tasks like the interest monitor."""
        logger.info("HeartFC_Chat starting asynchronous tasks...")
        await self.interest_manager.start_background_tasks()
        self._initialize_monitor_task()
        logger.info("HeartFC_Chat asynchronous tasks started.")

    def _initialize_monitor_task(self):
        """启动后台兴趣监控任务"""
        if self._interest_monitor_task is None or self._interest_monitor_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._interest_monitor_task = loop.create_task(self._interest_monitor_loop())
                logger.info(f"Interest monitor task created. Interval: {INTEREST_MONITOR_INTERVAL_SECONDS}s, Level Threshold: {INTEREST_LEVEL_REPLY_THRESHOLD}")
            except RuntimeError:
                 logger.error("Failed to create interest monitor task: No running event loop.")
                 raise
        else:
            logger.warning("Interest monitor task creation skipped: already running or exists.")

    async def _interest_monitor_loop(self):
        """后台任务，定期检查兴趣度变化并触发回复"""
        logger.info("Interest monitor loop starting...")
        await asyncio.sleep(0.3)
        while True:
            await asyncio.sleep(INTEREST_MONITOR_INTERVAL_SECONDS)
            try:
                interest_items_snapshot: List[tuple[str, InterestChatting]] = []
                stream_ids = list(self.interest_manager.interest_dict.keys())
                for stream_id in stream_ids:
                    chatting_instance = self.interest_manager.get_interest_chatting(stream_id)
                    if chatting_instance:
                        interest_items_snapshot.append((stream_id, chatting_instance))

                for stream_id, chatting_instance in interest_items_snapshot:
                    triggering_message = chatting_instance.last_triggering_message
                    current_interest = chatting_instance.get_interest()

                    # 添加调试日志，检查触发条件
                    # logger.debug(f"[兴趣监控][{stream_id}] 当前兴趣: {current_interest:.2f}, 阈值: {INTEREST_LEVEL_REPLY_THRESHOLD}, 触发消息存在: {triggering_message is not None}")

                    if current_interest > INTEREST_LEVEL_REPLY_THRESHOLD and triggering_message is not None:
                        logger.info(f"[{stream_id}] 检测到高兴趣度 ({current_interest:.2f} > {INTEREST_LEVEL_REPLY_THRESHOLD}). 基于消息 ID: {triggering_message.message_info.message_id} 的上下文触发回复") # 更新日志信息使其更清晰

                        chatting_instance.reset_trigger_info()
                        logger.debug(f"[{stream_id}] Trigger info reset before starting reply task.")

                        asyncio.create_task(self._process_triggered_reply(stream_id, triggering_message))

            except asyncio.CancelledError:
                logger.info("Interest monitor loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in interest monitor loop: {e}")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)

    async def _process_triggered_reply(self, stream_id: str, triggering_message: MessageRecv):
        """Helper coroutine to handle the processing of a triggered reply based on interest level."""
        try:
            logger.info(f"[{stream_id}] Starting level-triggered reply generation for message ID: {triggering_message.message_info.message_id}...")
            await self.trigger_reply_generation(triggering_message)

            # 在回复处理后降低兴趣度，降低固定值：新阈值的一半
            decrease_value = INTEREST_LEVEL_REPLY_THRESHOLD / 2
            self.interest_manager.decrease_interest(stream_id, value=decrease_value)
            post_trigger_interest = self.interest_manager.get_interest(stream_id)
            # 更新日志以反映降低的是基于新阈值的固定值
            logger.info(f"[{stream_id}] Interest decreased by fixed value {decrease_value:.2f} (LevelThreshold/2) after processing level-triggered reply. Current interest: {post_trigger_interest:.2f}")

        except Exception as e:
            logger.error(f"Error processing level-triggered reply for stream_id {stream_id}, context message_id {triggering_message.message_info.message_id}: {e}")
            logger.error(traceback.format_exc())

    async def _create_thinking_message(self, message: MessageRecv):
        """创建思考消息 (从 message 获取信息)"""
        chat = message.chat_stream
        if not chat:
             logger.error(f"Cannot create thinking message, chat_stream is None for message ID: {message.message_info.message_id}")
             return None
        userinfo = message.message_info.user_info # 发起思考的用户（即原始消息发送者）
        messageinfo = message.message_info # 原始消息信息
        bot_user_info = UserInfo(
            user_id=global_config.BOT_QQ,
            user_nickname=global_config.BOT_NICKNAME,
            platform=messageinfo.platform,
        )

        thinking_time_point = round(time.time(), 2)
        thinking_id = "mt" + str(thinking_time_point)
        thinking_message = MessageThinking(
            message_id=thinking_id,
            chat_stream=chat,
            bot_user_info=bot_user_info, # 思考消息的发出者是 bot
            reply=message, # 回复的是原始消息
            thinking_start_time=thinking_time_point,
        )

        MessageManager().add_message(thinking_message)

        return thinking_id

    async def _send_response_messages(self, message: MessageRecv, response_set: List[str], thinking_id) -> MessageSending:
        chat = message.chat_stream
        container = MessageManager().get_container(chat.stream_id)
        thinking_message = None
        for msg in container.messages:
            if isinstance(msg, MessageThinking) and msg.message_info.message_id == thinking_id:
                thinking_message = msg
                container.messages.remove(msg)
                break
        if not thinking_message:
            logger.warning("未找到对应的思考消息，可能已超时被移除")
            return None

        thinking_start_time = thinking_message.thinking_start_time
        message_set = MessageSet(chat, thinking_id)
        mark_head = False
        first_bot_msg = None
        for msg in response_set:
            message_segment = Seg(type="text", data=msg)
            bot_message = MessageSending(
                message_id=thinking_id,
                chat_stream=chat,
                bot_user_info=UserInfo(
                    user_id=global_config.BOT_QQ,
                    user_nickname=global_config.BOT_NICKNAME,
                    platform=message.message_info.platform, # 从传入的 message 获取 platform
                ),
                sender_info=message.message_info.user_info, # 发送给谁
                message_segment=message_segment,
                reply=message, # 回复原始消息
                is_head=not mark_head,
                is_emoji=False,
                thinking_start_time=thinking_start_time,
            )
            if not mark_head:
                mark_head = True
                first_bot_msg = bot_message
            message_set.add_message(bot_message)
        MessageManager().add_message(message_set)
        return first_bot_msg

    async def _handle_emoji(self, message: MessageRecv, response_set, send_emoji=""):
        """处理表情包 (从 message 获取信息)"""
        chat = message.chat_stream
        if send_emoji:
            emoji_raw = await emoji_manager.get_emoji_for_text(send_emoji)
        else:
            emoji_text_source = "".join(response_set) if response_set else ""
            emoji_raw = await emoji_manager.get_emoji_for_text(emoji_text_source)
        if emoji_raw:
            emoji_path, description = emoji_raw
            emoji_cq = image_path_to_base64(emoji_path)
            thinking_time_point = round(message.message_info.time, 2)
            message_segment = Seg(type="emoji", data=emoji_cq)
            bot_message = MessageSending(
                message_id="mt" + str(thinking_time_point),
                chat_stream=chat,
                bot_user_info=UserInfo(
                    user_id=global_config.BOT_QQ,
                    user_nickname=global_config.BOT_NICKNAME,
                    platform=message.message_info.platform,
                ),
                sender_info=message.message_info.user_info, # 发送给谁
                message_segment=message_segment,
                reply=message, # 回复原始消息
                is_head=False,
                is_emoji=True,
            )
            MessageManager().add_message(bot_message)

    async def _update_relationship(self, message: MessageRecv, response_set):
        """更新关系情绪"""
        ori_response = ",".join(response_set)
        stance, emotion = await self.gpt._get_emotion_tags(ori_response, message.processed_plain_text)
        await relationship_manager.calculate_update_relationship_value(
            chat_stream=message.chat_stream, label=emotion, stance=stance
        )
        self.mood_manager.update_mood_from_emotion(emotion, global_config.mood_intensity_factor)

    async def trigger_reply_generation(self, message: MessageRecv):
        """根据意愿阈值触发的实际回复生成和发送逻辑 (V3 - 简化参数)"""
        chat = message.chat_stream
        userinfo = message.message_info.user_info
        messageinfo = message.message_info

        timing_results = {}
        response_set = None
        thinking_id = None
        info_catcher = None

        try:
            try:
                with Timer("观察", timing_results):
                    sub_hf = heartflow.get_subheartflow(chat.stream_id)
                    if not sub_hf:
                        logger.warning(f"尝试观察时未找到 stream_id {chat.stream_id} 的 subheartflow")
                        return
                    await sub_hf.do_observe()
            except Exception as e:
                logger.error(f"心流观察失败: {e}")
                logger.error(traceback.format_exc())

            container = MessageManager().get_container(chat.stream_id)
            thinking_count = container.count_thinking_messages()
            max_thinking_messages = getattr(global_config, 'max_concurrent_thinking_messages', 3)
            if thinking_count >= max_thinking_messages:
                logger.warning(f"聊天流 {chat.stream_id} 已有 {thinking_count} 条思考消息，取消回复。触发消息: {message.processed_plain_text[:30]}...")
                return

            try:
                with Timer("创建思考消息", timing_results):
                    thinking_id = await self._create_thinking_message(message)
            except Exception as e:
                logger.error(f"心流创建思考消息失败: {e}")
                return
            if not thinking_id:
                logger.error("未能成功创建思考消息 ID，无法继续回复流程。")
                return

            logger.trace(f"创建捕捉器，thinking_id:{thinking_id}")
            info_catcher = info_catcher_manager.get_info_catcher(thinking_id)
            info_catcher.catch_decide_to_response(message)

            get_mid_memory_id = []
            tool_result_info = {}
            send_emoji = ""
            try:
                with Timer("思考前使用工具", timing_results):
                    tool_result = await self.tool_user.use_tool(
                        message.processed_plain_text,
                        userinfo.user_nickname,
                        chat,
                        heartflow.get_subheartflow(chat.stream_id),
                    )
                    if tool_result.get("used_tools", False):
                        if "structured_info" in tool_result:
                            tool_result_info = tool_result["structured_info"]
                            get_mid_memory_id = []
                            for tool_name, tool_data in tool_result_info.items():
                                if tool_name == "mid_chat_mem":
                                    for mid_memory in tool_data:
                                        get_mid_memory_id.append(mid_memory["content"])
                                if tool_name == "send_emoji":
                                    send_emoji = tool_data[0]["content"]
            except Exception as e:
                logger.error(f"思考前工具调用失败: {e}")
                logger.error(traceback.format_exc())

            current_mind, past_mind = "", ""
            try:
                with Timer("思考前脑内状态", timing_results):
                     sub_hf = heartflow.get_subheartflow(chat.stream_id)
                     if sub_hf:
                        current_mind, past_mind = await sub_hf.do_thinking_before_reply(
                            message_txt=message.processed_plain_text,
                            sender_info=userinfo,
                            chat_stream=chat,
                            obs_id=get_mid_memory_id,
                            extra_info=tool_result_info,
                        )
                     else:
                         logger.warning(f"尝试思考前状态时未找到 stream_id {chat.stream_id} 的 subheartflow")
            except Exception as e:
                logger.error(f"心流思考前脑内状态失败: {e}")
                logger.error(traceback.format_exc())
            if info_catcher:
                info_catcher.catch_afer_shf_step(timing_results.get("思考前脑内状态"), past_mind, current_mind)

            try:
                with Timer("生成回复", timing_results):
                    response_set = await self.gpt.generate_response(message, thinking_id)
            except Exception as e:
                 logger.error(f"GPT 生成回复失败: {e}")
                 logger.error(traceback.format_exc())
                 if info_catcher: info_catcher.done_catch()
                 return
            if info_catcher:
                info_catcher.catch_after_generate_response(timing_results.get("生成回复"))
            if not response_set:
                logger.info("回复生成失败，返回为空")
                if info_catcher: info_catcher.done_catch()
                return

            first_bot_msg = None
            try:
                with Timer("发送消息", timing_results):
                    first_bot_msg = await self._send_response_messages(message, response_set, thinking_id)
            except Exception as e:
                logger.error(f"心流发送消息失败: {e}")
            if info_catcher:
                info_catcher.catch_after_response(timing_results.get("发送消息"), response_set, first_bot_msg)
                info_catcher.done_catch()

            try:
                with Timer("处理表情包", timing_results):
                    if send_emoji:
                        logger.info(f"麦麦决定发送表情包{send_emoji}")
                        await self._handle_emoji(message, response_set, send_emoji)
            except Exception as e:
                logger.error(f"心流处理表情包失败: {e}")

            timing_str = " | ".join([f"{step}: {duration:.2f}秒" for step, duration in timing_results.items()])
            trigger_msg = message.processed_plain_text
            response_msg = " ".join(response_set) if response_set else "无回复"
            logger.info(f"回复任务完成: 触发消息: {trigger_msg[:20]}... | 思维消息: {response_msg[:20]}... | 性能计时: {timing_str}")

            if first_bot_msg:
                try:
                    with Timer("更新关系情绪", timing_results):
                        await self._update_relationship(message, response_set)
                except Exception as e:
                    logger.error(f"更新关系情绪失败: {e}")
                    logger.error(traceback.format_exc())

        except Exception as e:
            logger.error(f"回复生成任务失败 (trigger_reply_generation V3): {e}")
            logger.error(traceback.format_exc())

        finally:
            pass
