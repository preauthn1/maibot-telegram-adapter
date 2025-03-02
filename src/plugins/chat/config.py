from dataclasses import dataclass
from typing import Dict, Any, Optional, Set
import os
from nonebot.log import logger, default_format
import logging
import configparser
import tomli
import sys
from loguru import logger
from nonebot import get_driver



@dataclass
class BotConfig:
    """机器人配置类"""    
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
    
    build_memory_interval: int = 60  # 记忆构建间隔（秒）
    EMOJI_CHECK_INTERVAL: int = 120  # 表情包检查间隔（分钟）
    EMOJI_REGISTER_INTERVAL: int = 10  # 表情包注册间隔（分钟）
    
    API_USING: str = "siliconflow"  # 使用的API
    API_PAID: bool = False  # 是否使用付费API
    DEEPSEEK_MODEL_R1: str = "deepseek-reasoner"  # deepseek-R1模型
    DEEPSEEK_MODEL_V3: str = "deepseek-chat"  # deepseek-V3模型
    SILICONFLOW_MODEL_R1: str = "deepseek-ai/DeepSeek-R1"  # siliconflow-R1模型
    SILICONFLOW_MODEL_R1_DISTILL: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"  # siliconflow-R1蒸馏模型
    SILICONFLOW_MODEL_V3: str = "deepseek-ai/DeepSeek-V3"  # siliconflow-V3模型
    MODEL_R1_PROBABILITY: float = 0.8  # R1模型概率
    MODEL_V3_PROBABILITY: float = 0.1  # V3模型概率
    MODEL_R1_DISTILL_PROBABILITY: float = 0.1  # R1蒸馏模型概率
    
    enable_advance_output: bool = False  # 是否启用高级输出
    enable_kuuki_read: bool = True # 是否启用读空气功能
    
    @staticmethod
    def get_config_dir() -> str:
        """获取配置文件目录"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
        config_dir = os.path.join(root_dir, 'config')
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        return config_dir

    @staticmethod
    def create_default_config(config_path: str) -> None:
        """创建默认配置文件"""
        default_config = """[bot]
qq = 1  # 填入你的机器人QQ
nickname = "麦麦"  # 你希望bot被称呼的名字

[message]
min_text_length = 2 # 与麦麦聊天时麦麦只会回答文本大于等于此数的消息
max_context_size = 15 # 麦麦获得的上下文数量，超出数量后自动丢弃
emoji_chance = 0.2 # 麦麦使用表情包的概率

[emoji]
check_interval = 120
register_interval = 10

[cq_code]
enable_pic_translate = false

[response]
api_using = "siliconflow" # 选择大模型API，可选值为siliconflow,deepseek
api_paid = false # 是否使用付费api
model_r1_probability = 0.8 # 麦麦回答时选择R1模型的概率
model_v3_probability = 0.1 # 麦麦回答时选择V3模型的概率
model_r1_distill_probability = 0.1 # 麦麦回答时选择R1蒸馏模型的概率

[memory]
build_memory_interval = 300 # 记忆构建间隔

[others]
enable_advance_output = false # 开启后输出更多日志

[groups]
talk_allowed = [] # 可以回复消息的群
talk_frequency_down = [] # 降低回复频率的群
ban_user_id = [] # 禁止回复消息的QQ号
"""
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(default_config)
        logger.success(f"已创建默认配置文件: {config_path}")
    
    @classmethod
    def load_config(cls, config_path: str = None) -> "BotConfig":
        """从TOML配置文件加载配置"""
        config = cls()
        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                toml_dict = tomli.load(f)

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
                if response_config.get("api_using", config.API_PAID):
                    config.SILICONFLOW_MODEL_R1 = "Pro/deepseek-ai/DeepSeek-R1"
                    config.SILICONFLOW_MODEL_V3 = "Pro/deepseek-ai/DeepSeek-V3"
                
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
            
            logger.success(f"成功加载配置文件: {config_path}")
                
        return config 
    
# 获取配置文件路径

bot_config_floder_path = BotConfig.get_config_dir()
print(f"正在品鉴配置文件目录: {bot_config_floder_path}")
bot_config_path = os.path.join(bot_config_floder_path, "bot_config_dev.toml")
if not os.path.exists(bot_config_path):
    # 如果开发环境配置文件不存在，则使用默认配置文件
    bot_config_path = os.path.join(bot_config_floder_path, "bot_config.toml")
    logger.info("使用默认配置文件")
else:
    logger.info("已找到开发环境配置文件")

global_config = BotConfig.load_config(config_path=bot_config_path)


# config_dir = os.path.dirname(bot_config_path)

# logger.info(f"尝试从 {bot_config_path} 加载机器人配置")
# global_config = BotConfig.load_config(config_path=bot_config_path)

@dataclass
class LLMConfig:
    """机器人配置类"""
    # 基础配置
    SILICONFLOW_API_KEY: str = None
    SILICONFLOW_BASE_URL: str = None
    DEEP_SEEK_API_KEY: str = None
    DEEP_SEEK_BASE_URL: str = None

llm_config = LLMConfig()
config = get_driver().config
llm_config.SILICONFLOW_API_KEY = config.siliconflow_key
llm_config.SILICONFLOW_BASE_URL = config.siliconflow_base_url
llm_config.DEEP_SEEK_API_KEY = config.deep_seek_key
llm_config.DEEP_SEEK_BASE_URL = config.deep_seek_base_url


if not global_config.enable_advance_output:
    # logger.remove()
    pass

