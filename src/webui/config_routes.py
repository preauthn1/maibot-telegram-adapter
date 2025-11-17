"""
配置管理API路由
"""

import os
import tomlkit
from fastapi import APIRouter, HTTPException, Body
from typing import Any

from src.common.logger import get_logger
from src.config.config import Config, APIAdapterConfig, CONFIG_DIR
from src.config.official_configs import (
    BotConfig,
    PersonalityConfig,
    RelationshipConfig,
    ChatConfig,
    MessageReceiveConfig,
    EmojiConfig,
    ExpressionConfig,
    KeywordReactionConfig,
    ChineseTypoConfig,
    ResponsePostProcessConfig,
    ResponseSplitterConfig,
    TelemetryConfig,
    ExperimentalConfig,
    MaimMessageConfig,
    LPMMKnowledgeConfig,
    ToolConfig,
    MemoryConfig,
    DebugConfig,
    MoodConfig,
    VoiceConfig,
    JargonConfig,
)
from src.config.api_ada_configs import (
    ModelTaskConfig,
    ModelInfo,
    APIProvider,
)
from src.webui.config_schema import ConfigSchemaGenerator

logger = get_logger("webui")

router = APIRouter(prefix="/config", tags=["config"])


# ===== 架构获取接口 =====


@router.get("/schema/bot")
async def get_bot_config_schema():
    """获取麦麦主程序配置架构"""
    try:
        # Config 类包含所有子配置
        schema = ConfigSchemaGenerator.generate_config_schema(Config)
        return {"success": True, "schema": schema}
    except Exception as e:
        logger.error(f"获取配置架构失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置架构失败: {str(e)}")


@router.get("/schema/model")
async def get_model_config_schema():
    """获取模型配置架构（包含提供商和模型任务配置）"""
    try:
        schema = ConfigSchemaGenerator.generate_config_schema(APIAdapterConfig)
        return {"success": True, "schema": schema}
    except Exception as e:
        logger.error(f"获取模型配置架构失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取模型配置架构失败: {str(e)}")


# ===== 子配置架构获取接口 =====


@router.get("/schema/section/{section_name}")
async def get_config_section_schema(section_name: str):
    """
    获取指定配置节的架构

    支持的section_name:
    - bot: BotConfig
    - personality: PersonalityConfig
    - relationship: RelationshipConfig
    - chat: ChatConfig
    - message_receive: MessageReceiveConfig
    - emoji: EmojiConfig
    - expression: ExpressionConfig
    - keyword_reaction: KeywordReactionConfig
    - chinese_typo: ChineseTypoConfig
    - response_post_process: ResponsePostProcessConfig
    - response_splitter: ResponseSplitterConfig
    - telemetry: TelemetryConfig
    - experimental: ExperimentalConfig
    - maim_message: MaimMessageConfig
    - lpmm_knowledge: LPMMKnowledgeConfig
    - tool: ToolConfig
    - memory: MemoryConfig
    - debug: DebugConfig
    - mood: MoodConfig
    - voice: VoiceConfig
    - jargon: JargonConfig
    - model_task_config: ModelTaskConfig
    - api_provider: APIProvider
    - model_info: ModelInfo
    """
    section_map = {
        "bot": BotConfig,
        "personality": PersonalityConfig,
        "relationship": RelationshipConfig,
        "chat": ChatConfig,
        "message_receive": MessageReceiveConfig,
        "emoji": EmojiConfig,
        "expression": ExpressionConfig,
        "keyword_reaction": KeywordReactionConfig,
        "chinese_typo": ChineseTypoConfig,
        "response_post_process": ResponsePostProcessConfig,
        "response_splitter": ResponseSplitterConfig,
        "telemetry": TelemetryConfig,
        "experimental": ExperimentalConfig,
        "maim_message": MaimMessageConfig,
        "lpmm_knowledge": LPMMKnowledgeConfig,
        "tool": ToolConfig,
        "memory": MemoryConfig,
        "debug": DebugConfig,
        "mood": MoodConfig,
        "voice": VoiceConfig,
        "jargon": JargonConfig,
        "model_task_config": ModelTaskConfig,
        "api_provider": APIProvider,
        "model_info": ModelInfo,
    }

    if section_name not in section_map:
        raise HTTPException(status_code=404, detail=f"配置节 '{section_name}' 不存在")

    try:
        config_class = section_map[section_name]
        schema = ConfigSchemaGenerator.generate_schema(config_class, include_nested=False)
        return {"success": True, "schema": schema}
    except Exception as e:
        logger.error(f"获取配置节架构失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取配置节架构失败: {str(e)}")


# ===== 配置读取接口 =====


@router.get("/bot")
async def get_bot_config():
    """获取麦麦主程序配置"""
    try:
        config_path = os.path.join(CONFIG_DIR, "bot_config.toml")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = tomlkit.load(f)

        return {"success": True, "config": config_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {str(e)}")


@router.get("/model")
async def get_model_config():
    """获取模型配置（包含提供商和模型任务配置）"""
    try:
        config_path = os.path.join(CONFIG_DIR, "model_config.toml")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = tomlkit.load(f)

        return {"success": True, "config": config_data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"读取配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"读取配置文件失败: {str(e)}")


# ===== 配置更新接口 =====


@router.post("/bot")
async def update_bot_config(config_data: dict[str, Any] = Body(...)):
    """更新麦麦主程序配置"""
    try:
        # 验证配置数据
        try:
            Config.from_dict(config_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"配置数据验证失败: {str(e)}")

        # 保存配置文件
        config_path = os.path.join(CONFIG_DIR, "bot_config.toml")
        with open(config_path, "w", encoding="utf-8") as f:
            tomlkit.dump(config_data, f)

        logger.info("麦麦主程序配置已更新")
        return {"success": True, "message": "配置已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存配置文件失败: {str(e)}")


@router.post("/model")
async def update_model_config(config_data: dict[str, Any] = Body(...)):
    """更新模型配置"""
    try:
        # 验证配置数据
        try:
            APIAdapterConfig.from_dict(config_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"配置数据验证失败: {str(e)}")

        # 保存配置文件
        config_path = os.path.join(CONFIG_DIR, "model_config.toml")
        with open(config_path, "w", encoding="utf-8") as f:
            tomlkit.dump(config_data, f)

        logger.info("模型配置已更新")
        return {"success": True, "message": "配置已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"保存配置文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存配置文件失败: {str(e)}")


# ===== 配置节更新接口 =====


@router.post("/bot/section/{section_name}")
async def update_bot_config_section(section_name: str, section_data: Any = Body(...)):
    """更新麦麦主程序配置的指定节"""
    try:
        # 读取现有配置
        config_path = os.path.join(CONFIG_DIR, "bot_config.toml")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = tomlkit.load(f)

        # 更新指定节
        if section_name not in config_data:
            raise HTTPException(status_code=404, detail=f"配置节 '{section_name}' 不存在")

        config_data[section_name] = section_data

        # 验证完整配置
        try:
            Config.from_dict(config_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"配置数据验证失败: {str(e)}")

        # 保存配置
        with open(config_path, "w", encoding="utf-8") as f:
            tomlkit.dump(config_data, f)

        logger.info(f"配置节 '{section_name}' 已更新")
        return {"success": True, "message": f"配置节 '{section_name}' 已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置节失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置节失败: {str(e)}")


@router.post("/model/section/{section_name}")
async def update_model_config_section(section_name: str, section_data: Any = Body(...)):
    """更新模型配置的指定节"""
    try:
        # 读取现有配置
        config_path = os.path.join(CONFIG_DIR, "model_config.toml")
        if not os.path.exists(config_path):
            raise HTTPException(status_code=404, detail="配置文件不存在")

        with open(config_path, "r", encoding="utf-8") as f:
            config_data = tomlkit.load(f)

        # 更新指定节
        if section_name not in config_data:
            raise HTTPException(status_code=404, detail=f"配置节 '{section_name}' 不存在")

        config_data[section_name] = section_data

        # 验证完整配置
        try:
            APIAdapterConfig.from_dict(config_data)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"配置数据验证失败: {str(e)}")

        # 保存配置
        with open(config_path, "w", encoding="utf-8") as f:
            tomlkit.dump(config_data, f)

        logger.info(f"配置节 '{section_name}' 已更新")
        return {"success": True, "message": f"配置节 '{section_name}' 已保存"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新配置节失败: {e}")
        raise HTTPException(status_code=500, detail=f"更新配置节失败: {str(e)}")
