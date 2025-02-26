from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message as EventMessage, Bot
from .message import Message,MessageSet
from .config import BotConfig, global_config
from .storage import MessageStorage
from .llm_generator import LLMResponseGenerator
from .message_stream import MessageStream, MessageStreamContainer
from .topic_identifier import topic_identifier
from random import random
from nonebot.log import logger
from .group_info_manager import GroupInfoManager  # 导入群信息管理器
from .emoji_manager import emoji_manager  # 导入表情包管理器
import time
import os
from .cq_code import CQCode  # 导入CQCode模块
from .message_send_control import message_sender  # 导入消息发送控制器
from .message import Message_Thinking  # 导入 Message_Thinking 类
from .relationship_manager import relationship_manager
from .prompt_builder import prompt_builder
from .willing_manager import willing_manager  # 导入意愿管理器


class ChatBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.storage = MessageStorage()
        self.gpt = LLMResponseGenerator(config)
        self.group_info_manager = GroupInfoManager()  # 初始化群信息管理器
        self.bot = None  # bot 实例引用
        self._started = False
        
        self.emoji_chance = 0.2  # 发送表情包的基础概率
        self.message_streams = MessageStreamContainer()
        self.message_sender = message_sender
        
    async def _ensure_started(self):
        """确保所有任务已启动"""
        if not self._started:
            # 只保留必要的任务
            self._started = True
            
    def is_mentioned_bot(self, message: Message) -> bool:
        """检查消息是否提到了机器人"""
        keywords = ['麦麦']
        for keyword in keywords:
            if keyword in message.processed_plain_text:
                return True
        return False
                

    async def handle_message(self, event: GroupMessageEvent, bot: Bot) -> None:
        """处理收到的群消息"""
        
        if event.group_id not in self.config.talk_allowed_groups:
            return
        self.bot = bot  # 更新 bot 实例
        
        # 打印原始消息内容
        '''
        print(f"\n\033[1;33m[消息详情]\033[0m")
        # print(f"- 原始消息: {str(event.raw_message)}")
        print(f"- post_type: {event.post_type}")
        print(f"- sub_type: {event.sub_type}")
        print(f"- user_id: {event.user_id}")
        print(f"- message_type: {event.message_type}")
        # print(f"- message_id: {event.message_id}")
        # print(f"- message: {event.message}")
        print(f"- original_message: {event.original_message}")
        print(f"- raw_message: {event.raw_message}")
        # print(f"- font: {event.font}")
        print(f"- sender: {event.sender}")
        # print(f"- to_me: {event.to_me}")
        
        if event.reply:
            print(f"\n\033[1;33m[回复消息详情]\033[0m")
            # print(f"- message_id: {event.reply.message_id}")
            print(f"- message_type: {event.reply.message_type}")
            print(f"- sender: {event.reply.sender}")
            # print(f"- time: {event.reply.time}")
            print(f"- message: {event.reply.message}")
            print(f"- raw_message: {event.reply.raw_message}")
            # print(f"- original_message: {event.reply.original_message}")
        '''

        # 获取群组信息，发送消息的用户信息，并对数据库内容做一次更新
        
        group_info = await bot.get_group_info(group_id=event.group_id)
        await self.group_info_manager.update_group_info(
            group_id=event.group_id,
            group_name=group_info['group_name'],
            member_count=group_info['member_count']
        )
        
        
        sender_info = await bot.get_group_member_info(group_id=event.group_id, user_id=event.user_id, no_cache=True)
        
        # print(f"\033[1;32m[关系管理]\033[0m 更新关系: {sender_info}")
        
        await relationship_manager.update_relationship(user_id = event.user_id, data = sender_info)
        await relationship_manager.update_relationship_value(user_id = event.user_id, relationship_value = 0.5)
        print(f"\033[1;32m[关系管理]\033[0m 更新关系值: {relationship_manager.get_relationship(event.user_id).relationship_value}")
        
        
        
        message = Message(
            group_id=event.group_id,
            user_id=event.user_id,
            message_id=event.message_id,
            raw_message=str(event.original_message), 
            plain_text=event.get_plaintext(),
            reply_message=event.reply,
        )
        
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(message.time))

        topic = topic_identifier.identify_topic_jieba(message.processed_plain_text)
        print(f"\033[1;32m[主题识别]\033[0m 主题: {topic}")
        
        await self.storage.store_message(message, topic[0] if topic else None)
            
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(message.time))

        print(f"\033[1;34m[调试]\033[0m 当前消息是否是表情包: {message.is_emoji}")

        is_mentioned = self.is_mentioned_bot(message)
        reply_probability = willing_manager.change_reply_willing_received(
            event.group_id, 
            topic[0] if topic else None,
            is_mentioned,
            self.config,
            event.user_id,
            message.is_emoji
        )
        current_willing = willing_manager.get_willing(event.group_id)
        

        print(f"\033[1;32m[{current_time}][{message.group_name}]{message.user_nickname}:\033[0m {message.processed_plain_text}\033[1;36m[回复意愿:{current_willing:.2f}][概率:{reply_probability:.1f}]\033[0m")
        response = ""
        if random() < reply_probability:
            
            tinking_time_point = round(time.time(), 2)
            think_id = 'mt' + str(tinking_time_point)

            thinking_message = Message_Thinking(message=message,message_id=think_id)
            
            message_sender.send_temp_container.add_message(thinking_message)

            willing_manager.change_reply_willing_sent(thinking_message.group_id)
            # 生成回复
            response, emotion = await self.gpt.generate_response(message)
            
            # 如果生成了回复，发送并记录
        if response:
            message_set = MessageSet(event.group_id, self.config.BOT_QQ, think_id)
            if isinstance(response, list):
                # 将多条消息合并成一条
                for msg in response:
                    # print(f"\033[1;34m[调试]\033[0m 载入消息消息: {msg}")
                    # bot_response_time = round(time.time(), 2)
                    timepoint = tinking_time_point-0.3
                    bot_message = Message(
                        group_id=event.group_id,
                        user_id=self.config.BOT_QQ,
                        message_id=think_id,
                        message_based_id=event.message_id,
                        raw_message=msg,
                        plain_text=msg,
                        processed_plain_text=msg,
                        user_nickname="麦麦",
                        group_name=message.group_name,
                        time=timepoint
                    )
                    # print(f"\033[1;34m[调试]\033[0m 添加消息到消息组: {bot_message}")
                    message_set.add_message(bot_message)
                # print(f"\033[1;34m[调试]\033[0m 输入消息组: {message_set}")
                message_sender.send_temp_container.update_thinking_message(message_set)
            else:
                # bot_response_time = round(time.time(), 2)
                bot_message = Message(
                    group_id=event.group_id,
                    user_id=self.config.BOT_QQ,
                    message_id=think_id,
                    message_based_id=event.message_id,
                    raw_message=response,
                    plain_text=response,
                    processed_plain_text=response,
                    user_nickname="麦麦",
                    group_name=message.group_name,
                    time=tinking_time_point
                )
                # print(f"\033[1;34m[调试]\033[0m 更新单条消息: {bot_message}")
                message_sender.send_temp_container.update_thinking_message(bot_message)
    
            
            bot_response_time = tinking_time_point
            if random() < self.config.emoji_chance:
                emoji_path = await emoji_manager.get_emoji_for_emotion(emotion)
                if emoji_path:
                    emoji_cq = CQCode.create_emoji_cq(emoji_path)
                    
                    if random() < 0.5:
                        bot_response_time = tinking_time_point - 1
                    # else:
                        # bot_response_time = bot_response_time + 1
                        
                    bot_message = Message(
                            group_id=event.group_id,
                            user_id=self.config.BOT_QQ,
                            message_id=0,
                            raw_message=emoji_cq,
                            plain_text=emoji_cq,
                            processed_plain_text=emoji_cq,
                            user_nickname="麦麦",
                            group_name=message.group_name,
                            time=bot_response_time,
                            is_emoji=True
                        )
                    message_sender.send_temp_container.add_message(bot_message)
        
        # 如果收到新消息，提高回复意愿
        willing_manager.change_reply_willing_after_sent(event.group_id)