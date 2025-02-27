from dataclasses import dataclass
from typing import Dict, Any, Optional
import os
from nonebot.log import logger, default_format
import logging
import configparser  # 添加这行导入
import tomli  # 添加这行导入

# 禁用默认的日志输出
# logger.remove()

# # 只禁用 INFO 级别的日志输出到控制台
logging.getLogger('nonebot').handlers.clear()
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.WARNING)  # 只输出 WARNING 及以上级别
logging.getLogger('nonebot').addHandler(console_handler)
logging.getLogger('nonebot').setLevel(logging.WARNING)

@dataclass
class BotConfig:
    """机器人配置类"""
    
    # 基础配置
    MONGODB_HOST: str = "127.0.0.1"
    MONGODB_PORT: int = 27017
    DATABASE_NAME: str = "MegBot"
    
    BOT_QQ: Optional[int] = None
    BOT_NICKNAME: Optional[str] = None
    
    # 消息处理相关配置
    MIN_TEXT_LENGTH: int = 2  # 最小处理文本长度
    MAX_CONTEXT_SIZE: int = 15  # 上下文最大消息数
    emoji_chance: float = 0.2  # 发送表情包的基础概率
    
    read_allowed_groups = set()
    talk_allowed_groups = set()
    talk_frequency_down_groups = set()
    
    EMOJI_CHECK_INTERVAL: int = 120  # 表情包检查间隔（分钟）
    EMOJI_REGISTER_INTERVAL: int = 10  # 表情包注册间隔（分钟）
    
    MODEL_R1_PROBABILITY: float = 0.8  # R1模型概率
    MODEL_V3_PROBABILITY: float = 0.1  # V3模型概率
    MODEL_R1_DISTILL_PROBABILITY: float = 0.1  # R1蒸馏模型概率
    
    @classmethod
    def load_config(cls, config_path: str = "bot_config.toml") -> "BotConfig":
        """从TOML配置文件加载配置"""
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
            
            if "emoji" in toml_dict:
                emoji_config = toml_dict["emoji"]
                config.EMOJI_CHECK_INTERVAL = emoji_config.get("check_interval", config.EMOJI_CHECK_INTERVAL)
                config.EMOJI_REGISTER_INTERVAL = emoji_config.get("register_interval", config.EMOJI_REGISTER_INTERVAL)
            
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
            
            # 消息配置
            if "message" in toml_dict:
                msg_config = toml_dict["message"]
                config.MIN_TEXT_LENGTH = msg_config.get("min_text_length", config.MIN_TEXT_LENGTH)
                config.MAX_CONTEXT_SIZE = msg_config.get("max_context_size", config.MAX_CONTEXT_SIZE)
                config.emoji_chance = msg_config.get("emoji_chance", config.emoji_chance)
            
            # 群组配置
            if "groups" in toml_dict:
                groups_config = toml_dict["groups"]
                config.read_allowed_groups = set(groups_config.get("read_allowed", []))
                config.talk_allowed_groups = set(groups_config.get("talk_allowed", []))
                config.talk_frequency_down_groups = set(groups_config.get("talk_frequency_down", []))
            
            print(f"\033[1;32m成功加载配置文件: {config_path}\033[0m")
                
        return config 
    
global_config = BotConfig.load_config("./src/plugins/chat/bot_config.toml")

from dotenv import load_dotenv
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
load_dotenv(os.path.join(root_dir, '.env'))

@dataclass
class LLMConfig:
    """机器人配置类"""
    # 基础配置
    SILICONFLOW_API_KEY: str = None
    SILICONFLOW_BASE_URL: str = None

llm_config = LLMConfig()
llm_config.SILICONFLOW_API_KEY = os.getenv('SILICONFLOW_KEY')
llm_config.SILICONFLOW_BASE_URL = os.getenv('SILICONFLOW_BASE_URL')
