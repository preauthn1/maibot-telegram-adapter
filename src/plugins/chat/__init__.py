from nonebot import on_message, on_command, require, get_driver
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment
from nonebot.typing import T_State
from ...common.database import Database
from .config import global_config
import os
import asyncio
import random
from .relationship_manager import relationship_manager
from ..schedule.schedule_generator import bot_schedule
from .willing_manager import willing_manager


# 获取驱动器
driver = get_driver()

Database.initialize(
    global_config.MONGODB_HOST,
    global_config.MONGODB_PORT,
    global_config.DATABASE_NAME
)

print("\033[1;32m[初始化配置和数据库完成]\033[0m")


# 导入其他模块
from .bot import ChatBot
from .emoji_manager import emoji_manager
from .message_send_control import message_sender
from .relationship_manager import relationship_manager

# 初始化表情管理器
emoji_manager.initialize()

print(f"\033[1;32m正在唤醒{global_config.BOT_NICKNAME}......\033[0m")
# 创建机器人实例
chat_bot = ChatBot(global_config)

# 注册消息处理器
group_msg = on_message()

# 创建定时任务
scheduler = require("nonebot_plugin_apscheduler").scheduler

# 启动后台任务
@driver.on_startup
async def start_background_tasks():
    """启动后台任务"""
    # 只启动表情包管理任务
    asyncio.create_task(emoji_manager.start_periodic_check(interval_MINS=global_config.EMOJI_CHECK_INTERVAL))
    
    bot_schedule.print_schedule()

@driver.on_bot_connect
async def _(bot: Bot):
    """Bot连接成功时的处理"""
    print(f"\033[1;38;5;208m-----------{global_config.BOT_NICKNAME}成功连接！-----------\033[0m")
    message_sender.set_bot(bot)
    asyncio.create_task(message_sender.start_processor(bot))
    await willing_manager.ensure_started()
    print("\033[1;38;5;208m-----------消息发送器已启动！-----------\033[0m")
    
    asyncio.create_task(emoji_manager._periodic_scan(interval_MINS=global_config.EMOJI_REGISTER_INTERVAL))
    print("\033[1;38;5;208m-----------开始偷表情包！-----------\033[0m")
    # 启动消息发送控制任务
    
@driver.on_startup
async def init_relationships():
    """在 NoneBot2 启动时初始化关系管理器"""
    print("\033[1;32m[初始化]\033[0m 正在加载用户关系数据...")
    await relationship_manager.load_all_relationships()
    asyncio.create_task(relationship_manager._start_relationship_manager())

@group_msg.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State):
    await chat_bot.handle_message(event, bot)
    
@scheduler.scheduled_job("interval", seconds=300000, id="monitor_relationships")
async def monitor_relationships():
    """每15秒打印一次关系数据"""
    relationship_manager.print_all_relationships()

