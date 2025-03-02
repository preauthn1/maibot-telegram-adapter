from dataclasses import dataclass
from typing import Dict, Any, Optional, Set
import os
from nonebot.log import logger, default_format
import logging
import configparser
import tomli
import sys
from loguru import logger
from dotenv import load_dotenv



@dataclass
class BotConfig:
    """机器人配置类"""
    
    # 基础配置
    MONGODB_HOST: str = "mongodb"
    MONGODB_PORT: int = 27017
    DATABASE_NAME: str = "MegBot"
    MONGODB_USERNAME: Optional[str] = None  # 默认空值
    MONGODB_PASSWORD: Optional[str] = None  # 默认空值
    MONGODB_AUTH_SOURCE: Optional[str] = None  # 默认空值
    
    BOT_QQ: Optional[int] = 1
    BOT_NICKNAME: Optional[str] = None
    
    # 消息处理相关配置
    MIN_TEXT_LENGTH: int = 2  # 最小处理文本长度
    MAX_CONTEXT_SIZE: int = 15  # 上下文最大消息数
    emoji_chance: float = 0.2  # 发送表情包的基础概率
    
    ENABLE_PIC_TRANSLATE: bool = True  # 是否启用图片翻译
    
    talk_allowed_groups = set()
    talk_frequency_down_groups = set()
    ban_user_id = set()
    
    build_memory_interval: int = 600  # 记忆构建间隔（秒）
    EMOJI_CHECK_INTERVAL: int = 120  # 表情包检查间隔（分钟）
    EMOJI_REGISTER_INTERVAL: int = 10  # 表情包注册间隔（分钟）
    
    API_USING: str = "siliconflow"  # 使用的API
    MODEL_R1_PROBABILITY: float = 0.8  # R1模型概率
    MODEL_V3_PROBABILITY: float = 0.1  # V3模型概率
    MODEL_R1_DISTILL_PROBABILITY: float = 0.1  # R1蒸馏模型概率
    
    enable_advance_output: bool = False  # 是否启用高级输出
    enable_kuuki_read: bool = True # 是否启用读空气功能

    # 默认人设
    PROMPT_PERSONALITY=[
        "曾经是一个学习地质的女大学生，现在学习心理学和脑科学，你会刷贴吧，你正在浏览qq群",
        "是一个女大学生，你有黑色头发，你会刷小红书, 你正在浏览qq群"
    ]
    PROMPT_SCHEDULE_GEN="一个曾经学习地质,现在学习心理学和脑科学的女大学生，喜欢刷qq，贴吧，知乎和小红书"
    
    @staticmethod
    def get_default_config_path() -> str:
        """获取默认配置文件路径"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
        config_dir = os.path.join(root_dir, 'config')
        return os.path.join(config_dir, 'bot_config.toml')
    
    @classmethod
    def load_config(cls, config_path: str = None) -> "BotConfig":
        """从TOML配置文件加载配置"""
        if config_path is None:
            config_path = cls.get_default_config_path()
            logger.info(f"使用默认配置文件路径: {config_path}")
            
        config = cls()
        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                toml_dict = tomli.load(f)
            
            # 数据库配置
            if "database" in toml_dict:
                db_config = toml_dict["database"]
                config.MONGODB_HOST = db_config.get("host", config.MONGODB_HOST)
                config.MONGODB_PORT = db_config.get("port", config.MONGODB_PORT)
                config.DATABASE_NAME = db_config.get("name", config.DATABASE_NAME)
                config.MONGODB_USERNAME = db_config.get("username", config.MONGODB_USERNAME) or None  # 空字符串转为 None
                config.MONGODB_PASSWORD = db_config.get("password", config.MONGODB_PASSWORD) or None  # 空字符串转为 None
                config.MONGODB_AUTH_SOURCE = db_config.get("auth_source", config.MONGODB_AUTH_SOURCE) or None  # 空字符串转为 None
                
            if "emoji" in toml_dict:
                emoji_config = toml_dict["emoji"]
                config.EMOJI_CHECK_INTERVAL = emoji_config.get("check_interval", config.EMOJI_CHECK_INTERVAL)
                config.EMOJI_REGISTER_INTERVAL = emoji_config.get("register_interval", config.EMOJI_REGISTER_INTERVAL)
            
            if "cq_code" in toml_dict:
                cq_code_config = toml_dict["cq_code"]
                config.ENABLE_PIC_TRANSLATE = cq_code_config.get("enable_pic_translate", config.ENABLE_PIC_TRANSLATE)
            
            # 机器人基础配置
            if "bot" in toml_dict:
                bot_config = toml_dict["bot"]
                bot_qq = bot_config.get("qq")
                config.BOT_QQ = int(bot_qq)
                config.BOT_NICKNAME = bot_config.get("nickname", config.BOT_NICKNAME)
                
            if "response" in toml_dict:
                response_config = toml_dict["response"]
                config.MODEL_R1_PROBABILITY = response_config.get("model_r1_probability", config.MODEL_R1_PROBABILITY)
                config.MODEL_V3_PROBABILITY = response_config.get("model_v3_probability", config.MODEL_V3_PROBABILITY)
                config.MODEL_R1_DISTILL_PROBABILITY = response_config.get("model_r1_distill_probability", config.MODEL_R1_DISTILL_PROBABILITY)
                config.API_USING = response_config.get("api_using", config.API_USING)
                
            # 消息配置
            if "message" in toml_dict:
                msg_config = toml_dict["message"]
                config.MIN_TEXT_LENGTH = msg_config.get("min_text_length", config.MIN_TEXT_LENGTH)
                config.MAX_CONTEXT_SIZE = msg_config.get("max_context_size", config.MAX_CONTEXT_SIZE)
                config.emoji_chance = msg_config.get("emoji_chance", config.emoji_chance)
            
            if "memory" in toml_dict:
                memory_config = toml_dict["memory"]
                config.build_memory_interval = memory_config.get("build_memory_interval", config.build_memory_interval)
            
            # 群组配置
            if "groups" in toml_dict:
                groups_config = toml_dict["groups"]
                config.talk_allowed_groups = set(groups_config.get("talk_allowed", []))
                config.talk_frequency_down_groups = set(groups_config.get("talk_frequency_down", []))
                config.ban_user_id = set(groups_config.get("ban_user_id", []))
            
            if "others" in toml_dict:
                others_config = toml_dict["others"]
                config.enable_advance_output = others_config.get("enable_advance_output", config.enable_advance_output)

            # 自定义人设覆盖
            config.PROMPT_PERSONALITY=[
                "是一个计算机系大三女大学生，平时比较文静，喜欢打舞萌dx，你会刷贴吧，偶尔也会像贴吧老哥一样阴阳怪气，你正在浏览qq群",
                "是一个计算机系大三女大学生，平时比较文静，喜欢打舞萌dx，你有黑色头发，你会刷小红书, 你正在浏览qq群"
            ]
            config.PROMPT_SCHEDULE_GEN="一个计算机系大三女大学生，喜欢刷qq，贴吧，知乎和小红书，还喜欢打舞萌dx，经常下午或者晚上去江二打舞萌，睡得比较晚，有时会熬夜"

            
            logger.success(f"成功加载配置文件: {config_path}")
                
        return config 
    
# 获取配置文件路径
bot_config_path = BotConfig.get_default_config_path()
config_dir = os.path.dirname(bot_config_path)
env_path = os.path.join(config_dir, '.env')

logger.info(f"尝试从 {bot_config_path} 加载机器人配置")
global_config = BotConfig.load_config(config_path=bot_config_path)

# 加载环境变量

logger.info(f"尝试从 {env_path} 加载环境变量配置")
if os.path.exists(env_path):
    load_dotenv(env_path)
    logger.success("成功加载环境变量配置")
else:
    logger.error(f"环境变量配置文件不存在: {env_path}")

@dataclass
class LLMConfig:
    """机器人配置类"""
    # 基础配置
    SILICONFLOW_API_KEY: str = None
    SILICONFLOW_BASE_URL: str = None
    DEEP_SEEK_API_KEY: str = None
    DEEP_SEEK_BASE_URL: str = None

llm_config = LLMConfig()
llm_config.SILICONFLOW_API_KEY = os.getenv('SILICONFLOW_KEY')
llm_config.SILICONFLOW_BASE_URL = os.getenv('SILICONFLOW_BASE_URL')
llm_config.DEEP_SEEK_API_KEY = os.getenv('DEEP_SEEK_KEY')
llm_config.DEEP_SEEK_BASE_URL = os.getenv('DEEP_SEEK_BASE_URL')


if not global_config.enable_advance_output:
    # logger.remove()
    pass
