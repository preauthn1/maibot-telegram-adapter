from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Set
import os
import configparser
import tomli
import sys
from loguru import logger
from nonebot import get_driver
from packaging import version
from packaging.version import Version, InvalidVersion
from packaging.specifiers import SpecifierSet,InvalidSpecifier


@dataclass
class BotConfig:
    """机器人配置类"""    
    INNER_VERSION: SpecifierSet

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
    
    build_memory_interval: int = 30  # 记忆构建间隔（秒）
    forget_memory_interval: int = 300  # 记忆遗忘间隔（秒）
    EMOJI_CHECK_INTERVAL: int = 120  # 表情包检查间隔（分钟）
    EMOJI_REGISTER_INTERVAL: int = 10  # 表情包注册间隔（分钟）
    EMOJI_SAVE: bool = True  # 偷表情包
    EMOJI_CHECK: bool = False #是否开启过滤
    EMOJI_CHECK_PROMPT: str = "符合公序良俗" # 表情包过滤要求

    ban_words = set()

    max_response_length: int = 1024  # 最大回复长度
    
    # 模型配置
    llm_reasoning: Dict[str, str] = field(default_factory=lambda: {})
    llm_reasoning_minor: Dict[str, str] = field(default_factory=lambda: {})
    llm_normal: Dict[str, str] = field(default_factory=lambda: {})
    llm_normal_minor: Dict[str, str] = field(default_factory=lambda: {})
    llm_topic_judge: Dict[str, str] = field(default_factory=lambda: {})
    llm_summary_by_topic: Dict[str, str] = field(default_factory=lambda: {})
    llm_emotion_judge: Dict[str, str] = field(default_factory=lambda: {})
    embedding: Dict[str, str] = field(default_factory=lambda: {})
    vlm: Dict[str, str] = field(default_factory=lambda: {})
    moderation: Dict[str, str] = field(default_factory=lambda: {})

    MODEL_R1_PROBABILITY: float = 0.8  # R1模型概率
    MODEL_V3_PROBABILITY: float = 0.1  # V3模型概率
    MODEL_R1_DISTILL_PROBABILITY: float = 0.1  # R1蒸馏模型概率
    
    enable_advance_output: bool = False  # 是否启用高级输出
    enable_kuuki_read: bool = True # 是否启用读空气功能
    
    mood_update_interval: float = 1.0 # 情绪更新间隔 单位秒
    mood_decay_rate: float = 0.95 # 情绪衰减率
    mood_intensity_factor: float = 0.7 # 情绪强度因子

    # 默认人设
    PROMPT_PERSONALITY=[
        "曾经是一个学习地质的女大学生，现在学习心理学和脑科学，你会刷贴吧",
        "是一个女大学生，你有黑色头发，你会刷小红书"
    ]
    PROMPT_SCHEDULE_GEN="一个曾经学习地质,现在学习心理学和脑科学的女大学生，喜欢刷qq，贴吧，知乎和小红书"
    
    @staticmethod
    def get_config_dir() -> str:
        """获取配置文件目录"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
        config_dir = os.path.join(root_dir, 'config')
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)
        return config_dir
    
    @classmethod
    def convert_to_specifierset(value: str) -> SpecifierSet:
        """将 字符串 版本表达式转换成 SpecifierSet
        Args:
            value[str]: 版本表达式(字符串)
        Returns:
            SpecifierSet 
        """

        try:
            converted = SpecifierSet(value)
        except InvalidSpecifier as e:
            logger.error(
                f"{value} 分类使用了错误的版本约束表达式\n",
                "请阅读 https://semver.org/lang/zh-CN/ 修改代码"
            )
            exit(1)

        return converted
    
    @classmethod
    def get_config_version(cls, toml: dict) -> Version:
        """提取配置文件的 SpecifierSet 版本数据 
        Args:
            toml[dict]: 输入的配置文件字典
        Returns:
            Version 
        """

        if 'inner' in toml:
            try:
                config_version : str = toml["inner"]["version"]
            except KeyError as e:
                logger.error(f"配置文件中 inner 段 不存在 {e}, 这是错误的配置文件")
                exit(1)
        else:
            toml["inner"] = { "version": "0.0.0" }
            config_version = toml["inner"]["version"]
        
        try:
            ver = version.parse(config_version)
        except InvalidVersion as e:
            logger.error(
                "配置文件中 inner段 的 version 键是错误的版本描述\n"
                "请阅读 https://semver.org/lang/zh-CN/ 修改配置，并参考本项目指定的模板进行修改\n"
                "本项目在不同的版本下有不同的模板，请注意识别"
            )
            exit(1)

        return ver
    
    @classmethod
    def load_config(cls, config_path: str = None) -> "BotConfig":
        """从TOML配置文件加载配置"""
        config = cls()

        def personality(parent: dict):
            personality_config = parent['personality']
            personality = personality_config.get('prompt_personality')
            if len(personality) >= 2:
                logger.info(f"载入自定义人格:{personality}")
                config.PROMPT_PERSONALITY=personality_config.get('prompt_personality',config.PROMPT_PERSONALITY)
            logger.info(f"载入自定义日程prompt:{personality_config.get('prompt_schedule',config.PROMPT_SCHEDULE_GEN)}")
            config.PROMPT_SCHEDULE_GEN=personality_config.get('prompt_schedule',config.PROMPT_SCHEDULE_GEN)

        def emoji(parent: dict):
            emoji_config = parent["emoji"]
            config.EMOJI_CHECK_INTERVAL = emoji_config.get("check_interval", config.EMOJI_CHECK_INTERVAL)
            config.EMOJI_REGISTER_INTERVAL = emoji_config.get("register_interval", config.EMOJI_REGISTER_INTERVAL)
            config.EMOJI_CHECK_PROMPT = emoji_config.get('check_prompt',config.EMOJI_CHECK_PROMPT)
            config.EMOJI_SAVE = emoji_config.get('auto_save',config.EMOJI_SAVE)
            config.EMOJI_CHECK = emoji_config.get('enable_check',config.EMOJI_CHECK)
        
        def cq_code(parent: dict):
            cq_code_config = parent["cq_code"]
            config.ENABLE_PIC_TRANSLATE = cq_code_config.get("enable_pic_translate", config.ENABLE_PIC_TRANSLATE)
        
        def bot(parent: dict):
            # 机器人基础配置
            bot_config = parent["bot"]
            bot_qq = bot_config.get("qq")
            config.BOT_QQ = int(bot_qq)
            config.BOT_NICKNAME = bot_config.get("nickname", config.BOT_NICKNAME)

        def response(parent: dict):
            response_config = parent["response"]
            config.MODEL_R1_PROBABILITY = response_config.get("model_r1_probability", config.MODEL_R1_PROBABILITY)
            config.MODEL_V3_PROBABILITY = response_config.get("model_v3_probability", config.MODEL_V3_PROBABILITY)
            config.MODEL_R1_DISTILL_PROBABILITY = response_config.get("model_r1_distill_probability", config.MODEL_R1_DISTILL_PROBABILITY)
            config.max_response_length = response_config.get("max_response_length", config.max_response_length)
        
        def model(parent: dict):
            # 加载模型配置
            model_config = parent["model"]
            config_version : Version = cls.get_config_version(parent)

            config_list = [
                "llm_reasoning",
                "llm_reasoning_minor",
                "llm_normal",
                "llm_normal_minor",
                "llm_topic_judge",
                "llm_summary_by_topic",
                "llm_emotion_judge",
                "vlm",
                "embedding",
                "moderation"
            ]

            for item in config_list:
                if item in model_config:
                    cfg_item = model_config[item]

                    # base_url 的例子： SILICONFLOW_BASE_URL
                    # key 的例子： SILICONFLOW_KEY
                    cfg_target = {
                        "name" : "",
                        "base_url" : "", 
                        "key" : "",
                        "pri_in" : 0,
                        "pri_out" : 0
                    }

                    if config_version in SpecifierSet("<0.0.0"):
                        cfg_target = cfg_item

                    elif config_version in SpecifierSet(">=0.0.1"):
                        stable_item = ["name","pri_in","pri_out"]
                        for i in stable_item:
                            cfg_target[i] = cfg_item[i]

                        provider = cfg_item["provider"]
                        
                        cfg_target["base_url"] = f"{provider}_BASE_URL"
                        cfg_target["key"] = f"{provider}_KEY"

                    
                    # 如果 列表中的项目在 model_config 中，利用反射来设置对应项目
                    setattr(config,item,cfg_target)

        def message(parent: dict):
            msg_config = parent["message"]
            config.MIN_TEXT_LENGTH = msg_config.get("min_text_length", config.MIN_TEXT_LENGTH)
            config.MAX_CONTEXT_SIZE = msg_config.get("max_context_size", config.MAX_CONTEXT_SIZE)
            config.emoji_chance = msg_config.get("emoji_chance", config.emoji_chance)
            config.ban_words=msg_config.get("ban_words",config.ban_words)

        def memory(parent: dict):
            memory_config = parent["memory"]
            config.build_memory_interval = memory_config.get("build_memory_interval", config.build_memory_interval)
            config.forget_memory_interval = memory_config.get("forget_memory_interval", config.forget_memory_interval)

        def mood(parent: dict):
            mood_config = parent["mood"]
            config.mood_update_interval = mood_config.get("mood_update_interval", config.mood_update_interval)
            config.mood_decay_rate = mood_config.get("mood_decay_rate", config.mood_decay_rate)
            config.mood_intensity_factor = mood_config.get("mood_intensity_factor", config.mood_intensity_factor)

        def groups(parent: dict):
            groups_config = parent["groups"]
            config.talk_allowed_groups = set(groups_config.get("talk_allowed", []))
            config.talk_frequency_down_groups = set(groups_config.get("talk_frequency_down", []))
            config.ban_user_id = set(groups_config.get("ban_user_id", []))

        def others(parent: dict):
            others_config = parent["others"]
            config.enable_advance_output = others_config.get("enable_advance_output", config.enable_advance_output)
            config.enable_kuuki_read = others_config.get("enable_kuuki_read", config.enable_kuuki_read)

        # 版本表达式：>=1.0.0,<2.0.0
        include_configs = {
            "personality": {
                "func": personality,
                "support": ">=0.0.0"
            },
            "emoji": {
                "func": emoji,
                "support": ">=0.0.0"
            },
            "cq_code": {
                "func": cq_code,
                "support": ">=0.0.0"
            },
            "bot": {
                "func": bot,
                "support": ">=0.0.0"
            },
            "response": {
                "func": response,
                "support": ">=0.0.0"
            },
            "model": {
                "func": model,
                "support": ">=0.0.0"
            },
            "message": {
                "func": message,
                "support": ">=0.0.0"
            },
            "memory": {
                "func": memory,
                "support": ">=0.0.0"
            },
            "mood": {
                "func": mood,
                "support": ">=0.0.0"
            },
            "groups": {
                "func": groups,
                "support": ">=0.0.0"
            },
            "others": {
                "func": others,
                "support": ">=0.0.0"
            }
        }

        # 原地修改，将 字符串版本表达式 转换成 版本对象
        for key in include_configs:
            item_support = include_configs[key]["support"]
            include_configs[key]["support"] = cls.convert_to_specifierset(item_support)

        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                toml_dict = tomli.load(f)
                
                # 获取配置文件版本
                config_version : Version = cls.get_config_version(toml_dict)

                # 如果在配置中找到了需要的项，调用对应项的闭包函数处理
                for key in include_configs:
                    if key in toml_dict:
                        group_specifierset: SpecifierSet = toml_dict[key]["support"]

                        # 检查配置文件版本是否在支持范围内
                        if config_version in group_specifierset:
                            # 如果版本在支持范围内，检查是否在支持的末端
                            if config_version == group_specifierset.filter([config_version])[-1]:
                                logger.warning(
                                    f"配置文件中的 '{key}' 字段的版本 ({config_version}) 已接近支持范围的末端。\n"
                                    f"未来版本可能会移除对该字段的支持。"
                                )
                            include_configs[key]["func"](toml_dict)

                        else:
                            # 如果版本不在支持范围内，崩溃并提示用户
                            logger.error(
                                f"配置文件中的 '{key}' 字段的版本 ({config_version}) 不在支持范围内。\n"
                                f"当前程序仅支持以下版本范围: {group_specifierset}"
                            )
                            exit(1)

                    else:
                        # 如果用户根本没有需要的配置项，提示缺少配置
                        logger.error(f"配置文件中缺少必需的字段: '{key}'")
                        exit(1)

                logger.success(f"成功加载配置文件: {config_path}")
                
        return config 
    
# 获取配置文件路径
bot_config_floder_path = BotConfig.get_config_dir()
print(f"正在品鉴配置文件目录: {bot_config_floder_path}")

bot_config_path = os.path.join(bot_config_floder_path, "bot_config.toml")

if os.path.exists(bot_config_path):
    # 如果开发环境配置文件不存在，则使用默认配置文件
    print(f"异常的新鲜，异常的美味: {bot_config_path}")
    logger.info("使用bot配置文件")
else:
    # 配置文件不存在
    logger.error("配置文件不存在，请检查路径: {bot_config_path}")
    raise FileNotFoundError(f"配置文件不存在: {bot_config_path}")

global_config = BotConfig.load_config(config_path=bot_config_path)


if not global_config.enable_advance_output:
    logger.remove()
    pass

