"""
表情API模块

提供表情包相关功能，采用标准Python包设计模式
使用方式：
    from src.plugin_system.apis import emoji_api
    result = await emoji_api.get_by_description("开心")
    count = emoji_api.get_count()
"""

import random
import base64
import os
import uuid
import time

from typing import Optional, Tuple, List, Dict, Any
from src.common.logger import get_logger
from src.chat.emoji_system.emoji_manager import get_emoji_manager, EMOJI_DIR
from src.chat.utils.utils_image import image_path_to_base64, base64_to_image

logger = get_logger("emoji_api")


# =============================================================================
# 表情包获取API函数
# =============================================================================


async def get_by_description(description: str) -> Optional[Tuple[str, str, str]]:
    """根据描述选择表情包

    Args:
        description: 表情包的描述文本，例如"开心"、"难过"、"愤怒"等

    Returns:
        Optional[Tuple[str, str, str]]: (base64编码, 表情包描述, 匹配的情感标签) 或 None

    Raises:
        ValueError: 如果描述为空字符串
        TypeError: 如果描述不是字符串类型
    """
    if not description:
        raise ValueError("描述不能为空")
    if not isinstance(description, str):
        raise TypeError("描述必须是字符串类型")
    try:
        logger.debug(f"[EmojiAPI] 根据描述获取表情包: {description}")

        emoji_manager = get_emoji_manager()
        emoji_result = await emoji_manager.get_emoji_for_text(description)

        if not emoji_result:
            logger.warning(f"[EmojiAPI] 未找到匹配描述 '{description}' 的表情包")
            return None

        emoji_path, emoji_description, matched_emotion = emoji_result
        emoji_base64 = image_path_to_base64(emoji_path)

        if not emoji_base64:
            logger.error(f"[EmojiAPI] 无法将表情包文件转换为base64: {emoji_path}")
            return None

        logger.debug(f"[EmojiAPI] 成功获取表情包: {emoji_description}, 匹配情感: {matched_emotion}")
        return emoji_base64, emoji_description, matched_emotion

    except Exception as e:
        logger.error(f"[EmojiAPI] 获取表情包失败: {e}")
        return None


async def get_random(count: Optional[int] = 1) -> List[Tuple[str, str, str]]:
    """随机获取指定数量的表情包

    Args:
        count: 要获取的表情包数量，默认为1

    Returns:
        List[Tuple[str, str, str]]: 包含(base64编码, 表情包描述, 随机情感标签)的元组列表，失败则返回空列表

    Raises:
        TypeError: 如果count不是整数类型
        ValueError: 如果count为负数
    """
    if not isinstance(count, int):
        raise TypeError("count 必须是整数类型")
    if count < 0:
        raise ValueError("count 不能为负数")
    if count == 0:
        logger.warning("[EmojiAPI] count 为0，返回空列表")
        return []

    try:
        emoji_manager = get_emoji_manager()
        all_emojis = emoji_manager.emoji_objects

        if not all_emojis:
            logger.warning("[EmojiAPI] 没有可用的表情包")
            return []

        # 过滤有效表情包
        valid_emojis = [emoji for emoji in all_emojis if not emoji.is_deleted]
        if not valid_emojis:
            logger.warning("[EmojiAPI] 没有有效的表情包")
            return []

        if len(valid_emojis) < count:
            logger.warning(
                f"[EmojiAPI] 有效表情包数量 ({len(valid_emojis)}) 少于请求的数量 ({count})，将返回所有有效表情包"
            )
            count = len(valid_emojis)

        # 随机选择
        selected_emojis = random.sample(valid_emojis, count)

        results = []
        for selected_emoji in selected_emojis:
            emoji_base64 = image_path_to_base64(selected_emoji.full_path)

            if not emoji_base64:
                logger.error(f"[EmojiAPI] 无法转换表情包为base64: {selected_emoji.full_path}")
                continue

            matched_emotion = random.choice(selected_emoji.emotion) if selected_emoji.emotion else "随机表情"

            # 记录使用次数
            emoji_manager.record_usage(selected_emoji.hash)
            results.append((emoji_base64, selected_emoji.description, matched_emotion))

        if not results and count > 0:
            logger.warning("[EmojiAPI] 随机获取表情包失败，没有一个可以成功处理")
            return []

        logger.debug(f"[EmojiAPI] 成功获取 {len(results)} 个随机表情包")
        return results

    except Exception as e:
        logger.error(f"[EmojiAPI] 获取随机表情包失败: {e}")
        return []


async def get_by_emotion(emotion: str) -> Optional[Tuple[str, str, str]]:
    """根据情感标签获取表情包

    Args:
        emotion: 情感标签，如"happy"、"sad"、"angry"等

    Returns:
        Optional[Tuple[str, str, str]]: (base64编码, 表情包描述, 匹配的情感标签) 或 None

    Raises:
        ValueError: 如果情感标签为空字符串
        TypeError: 如果情感标签不是字符串类型
    """
    if not emotion:
        raise ValueError("情感标签不能为空")
    if not isinstance(emotion, str):
        raise TypeError("情感标签必须是字符串类型")
    try:
        logger.info(f"[EmojiAPI] 根据情感获取表情包: {emotion}")

        emoji_manager = get_emoji_manager()
        all_emojis = emoji_manager.emoji_objects

        # 筛选匹配情感的表情包
        matching_emojis = []
        matching_emojis.extend(
            emoji_obj
            for emoji_obj in all_emojis
            if not emoji_obj.is_deleted and emotion.lower() in [e.lower() for e in emoji_obj.emotion]
        )
        if not matching_emojis:
            logger.warning(f"[EmojiAPI] 未找到匹配情感 '{emotion}' 的表情包")
            return None

        # 随机选择匹配的表情包
        selected_emoji = random.choice(matching_emojis)
        emoji_base64 = image_path_to_base64(selected_emoji.full_path)

        if not emoji_base64:
            logger.error(f"[EmojiAPI] 无法转换表情包为base64: {selected_emoji.full_path}")
            return None

        # 记录使用次数
        emoji_manager.record_usage(selected_emoji.hash)

        logger.info(f"[EmojiAPI] 成功获取情感表情包: {selected_emoji.description}")
        return emoji_base64, selected_emoji.description, emotion

    except Exception as e:
        logger.error(f"[EmojiAPI] 根据情感获取表情包失败: {e}")
        return None


# =============================================================================
# 表情包信息查询API函数
# =============================================================================


def get_count() -> int:
    """获取表情包数量

    Returns:
        int: 当前可用的表情包数量
    """
    try:
        emoji_manager = get_emoji_manager()
        return emoji_manager.emoji_num
    except Exception as e:
        logger.error(f"[EmojiAPI] 获取表情包数量失败: {e}")
        return 0


def get_info():
    """获取表情包系统信息

    Returns:
        dict: 包含表情包数量、最大数量、可用数量信息
    """
    try:
        emoji_manager = get_emoji_manager()
        return {
            "current_count": emoji_manager.emoji_num,
            "max_count": emoji_manager.emoji_num_max,
            "available_emojis": len([e for e in emoji_manager.emoji_objects if not e.is_deleted]),
        }
    except Exception as e:
        logger.error(f"[EmojiAPI] 获取表情包信息失败: {e}")
        return {"current_count": 0, "max_count": 0, "available_emojis": 0}


def get_emotions() -> List[str]:
    """获取所有可用的情感标签

    Returns:
        list: 所有表情包的情感标签列表（去重）
    """
    try:
        emoji_manager = get_emoji_manager()
        emotions = set()

        for emoji_obj in emoji_manager.emoji_objects:
            if not emoji_obj.is_deleted and emoji_obj.emotion:
                emotions.update(emoji_obj.emotion)

        return sorted(list(emotions))
    except Exception as e:
        logger.error(f"[EmojiAPI] 获取情感标签失败: {e}")
        return []


async def get_all() -> List[Tuple[str, str, str]]:
    """获取所有表情包

    Returns:
        List[Tuple[str, str, str]]: 包含(base64编码, 表情包描述, 随机情感标签)的元组列表
    """
    try:
        emoji_manager = get_emoji_manager()
        all_emojis = emoji_manager.emoji_objects

        if not all_emojis:
            logger.warning("[EmojiAPI] 没有可用的表情包")
            return []

        results = []
        for emoji_obj in all_emojis:
            if emoji_obj.is_deleted:
                continue

            emoji_base64 = image_path_to_base64(emoji_obj.full_path)

            if not emoji_base64:
                logger.error(f"[EmojiAPI] 无法转换表情包为base64: {emoji_obj.full_path}")
                continue

            matched_emotion = random.choice(emoji_obj.emotion) if emoji_obj.emotion else "随机表情"
            results.append((emoji_base64, emoji_obj.description, matched_emotion))

        logger.debug(f"[EmojiAPI] 成功获取 {len(results)} 个表情包")
        return results

    except Exception as e:
        logger.error(f"[EmojiAPI] 获取所有表情包失败: {e}")
        return []


def get_descriptions() -> List[str]:
    """获取所有表情包描述

    Returns:
        list: 所有可用表情包的描述列表
    """
    try:
        emoji_manager = get_emoji_manager()
        descriptions = []

        descriptions.extend(
            emoji_obj.description
            for emoji_obj in emoji_manager.emoji_objects
            if not emoji_obj.is_deleted and emoji_obj.description
        )
        return descriptions
    except Exception as e:
        logger.error(f"[EmojiAPI] 获取表情包描述失败: {e}")
        return []


# =============================================================================
# 表情包注册API函数
# =============================================================================


async def register_emoji(image_base64: str, filename: Optional[str] = None) -> Dict[str, Any]:
    """注册新的表情包

    Args:
        image_base64: 图片的base64编码
        filename: 可选的文件名，如果未提供则自动生成

    Returns:
        Dict[str, Any]: 注册结果，包含以下字段：
            - success: bool, 是否成功注册
            - message: str, 结果消息
            - description: Optional[str], 表情包描述（成功时）
            - emotions: Optional[List[str]], 情感标签列表（成功时）
            - replaced: Optional[bool], 是否替换了旧表情包（成功时）
            - hash: Optional[str], 表情包哈希值（成功时）

    Raises:
        ValueError: 如果base64为空或无效
        TypeError: 如果参数类型不正确
    """
    if not image_base64:
        raise ValueError("图片base64编码不能为空")
    if not isinstance(image_base64, str):
        raise TypeError("image_base64必须是字符串类型")
    if filename is not None and not isinstance(filename, str):
        raise TypeError("filename必须是字符串类型或None")

    try:
        logger.info(f"[EmojiAPI] 开始注册表情包，文件名: {filename or '自动生成'}")

        # 1. 获取emoji管理器并检查容量
        emoji_manager = get_emoji_manager()
        count_before = emoji_manager.emoji_num
        max_count = emoji_manager.emoji_num_max

        # 2. 检查是否可以注册（未达到上限或启用替换）
        can_register = count_before < max_count or (
            count_before >= max_count and emoji_manager.emoji_num_max_reach_deletion
        )

        if not can_register:
            return {
                "success": False,
                "message": f"表情包数量已达上限({count_before}/{max_count})且未启用替换功能",
                "description": None,
                "emotions": None,
                "replaced": None,
                "hash": None
            }

        # 3. 确保emoji目录存在
        os.makedirs(EMOJI_DIR, exist_ok=True)

        # 4. 生成文件名
        if not filename:
            # 基于时间戳和UUID生成唯一文件名
            timestamp = int(time.time())
            unique_id = str(uuid.uuid4())[:8]
            filename = f"emoji_{timestamp}_{unique_id}"

        # 确保文件名有扩展名
        if not filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
            filename = f"{filename}.png"  # 默认使用png格式

        # 5. 保存base64图片到emoji目录
        temp_file_path = os.path.join(EMOJI_DIR, filename)

        try:
            # 解码base64并保存图片
            if not base64_to_image(image_base64, temp_file_path):
                logger.error(f"[EmojiAPI] 无法保存base64图片到文件: {temp_file_path}")
                return {
                    "success": False,
                    "message": "无法保存图片文件",
                    "description": None,
                    "emotions": None,
                    "replaced": None,
                    "hash": None
                }

            logger.debug(f"[EmojiAPI] 图片已保存到临时文件: {temp_file_path}")

        except Exception as save_error:
            logger.error(f"[EmojiAPI] 保存图片文件失败: {save_error}")
            return {
                "success": False,
                "message": f"保存图片文件失败: {str(save_error)}",
                "description": None,
                "emotions": None,
                "replaced": None,
                "hash": None
            }

        # 6. 调用注册方法
        register_success = await emoji_manager.register_emoji_by_filename(filename)

        # 7. 清理临时文件（如果注册失败但文件还存在）
        if not register_success and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.debug(f"[EmojiAPI] 已清理临时文件: {temp_file_path}")
            except Exception as cleanup_error:
                logger.warning(f"[EmojiAPI] 清理临时文件失败: {cleanup_error}")

        # 8. 构建返回结果
        if register_success:
            count_after = emoji_manager.emoji_num
            replaced = count_after <= count_before  # 如果数量没增加，说明是替换

            # 尝试获取新注册的表情包信息
            new_emoji_info = None
            if count_after > count_before or replaced:
                # 获取最新的表情包信息
                try:
                    # 通过文件名查找新注册的表情包（注意：文件名在注册后可能已经改变）
                    for emoji_obj in reversed(emoji_manager.emoji_objects):
                        if not emoji_obj.is_deleted and (
                            emoji_obj.filename == filename or  # 直接匹配
                            (hasattr(emoji_obj, 'full_path') and filename in emoji_obj.full_path)  # 路径包含匹配
                        ):
                            new_emoji_info = emoji_obj
                            break
                except Exception as find_error:
                    logger.warning(f"[EmojiAPI] 查找新注册表情包信息失败: {find_error}")

            description = new_emoji_info.description if new_emoji_info else None
            emotions = new_emoji_info.emotion if new_emoji_info else None
            emoji_hash = new_emoji_info.hash if new_emoji_info else None

            return {
                "success": True,
                "message": f"表情包注册成功 {'(替换旧表情包)' if replaced else '(新增表情包)'}",
                "description": description,
                "emotions": emotions,
                "replaced": replaced,
                "hash": emoji_hash
            }
        else:
            return {
                "success": False,
                "message": "表情包注册失败，可能因为重复、格式不支持或审核未通过",
                "description": None,
                "emotions": None,
                "replaced": None,
                "hash": None
            }

    except Exception as e:
        logger.error(f"[EmojiAPI] 注册表情包时发生异常: {e}")
        return {
            "success": False,
            "message": f"注册过程中发生错误: {str(e)}",
            "description": None,
            "emotions": None,
            "replaced": None,
            "hash": None
        }
