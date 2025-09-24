import random
from typing import List, Tuple, Type, Any
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseAction,
    BaseCommand,
    BaseTool,
    ComponentInfo,
    ActionActivationType,
    ConfigField,
    BaseEventHandler,
    EventType,
    MaiMessages,
    ToolParamType,
    ReplyContentType,
    emoji_api,
)
from maim_message import Seg
from src.config.config import global_config
from src.common.logger import get_logger
logger = get_logger("emoji_manage_plugin")

class AddEmojiCommand(BaseCommand):
    command_name = "add_emoji"
    command_description = "添加表情包"
    command_pattern = r".*/emoji add.*"

    async def execute(self) -> Tuple[bool, str, bool]:
        # 查找消息中的表情包
        logger.info(f"查找消息中的表情包: {self.message.message_segment}")
        
        emoji_base64_list = self.find_and_return_emoji_in_message(self.message.message_segment)

        if not emoji_base64_list:
            return False, "未在消息中找到表情包或图片", False

        # 注册找到的表情包
        success_count = 0
        fail_count = 0
        results = []

        for i, emoji_base64 in enumerate(emoji_base64_list):
            try:
                # 使用emoji_api注册表情包
                result = await emoji_api.register_emoji(emoji_base64, filename=f"emoji_{i+1}")

                if result["success"]:
                    success_count += 1
                    description = result.get("description", "未知描述")
                    emotions = result.get("emotions", [])
                    replaced = result.get("replaced", False)

                    result_msg = f"表情包 {i+1} 注册成功{'(替换旧表情包)' if replaced else '(新增表情包)'}"
                    if description:
                        result_msg += f"\n描述: {description}"
                    if emotions:
                        result_msg += f"\n情感标签: {', '.join(emotions)}"

                    results.append(result_msg)
                else:
                    fail_count += 1
                    error_msg = result.get("message", "注册失败")
                    results.append(f"表情包 {i+1} 注册失败: {error_msg}")

            except Exception as e:
                fail_count += 1
                results.append(f"表情包 {i+1} 注册时发生错误: {str(e)}")

        # 构建返回消息
        total_count = success_count + fail_count
        summary_msg = f"表情包注册完成: 成功 {success_count} 个，失败 {fail_count} 个，共处理 {total_count} 个"

        # 如果有结果详情，添加到返回消息中
        if results:
            details_msg = "\n" + "\n".join(results)
            final_msg = summary_msg + details_msg
        else:
            final_msg = summary_msg

        return success_count > 0, final_msg, success_count > 0

    def find_and_return_emoji_in_message(self, message_segments) -> List[str]:
        emoji_base64_list = []

        # 处理单个Seg对象的情况
        if isinstance(message_segments, Seg):
            if message_segments.type == "emoji":
                emoji_base64_list.append(message_segments.data)
            elif message_segments.type == "image":
                # 假设图片数据是base64编码的
                emoji_base64_list.append(message_segments.data)
            elif message_segments.type == "seglist":
                # 递归处理嵌套的Seg列表
                emoji_base64_list.extend(self.find_and_return_emoji_in_message(message_segments.data))
            return emoji_base64_list

        # 处理Seg列表的情况
        for seg in message_segments:
            if seg.type == "emoji":
                emoji_base64_list.append(seg.data)
            elif seg.type == "image":
                # 假设图片数据是base64编码的
                emoji_base64_list.append(seg.data)
            elif seg.type == "seglist":
                # 递归处理嵌套的Seg列表
                emoji_base64_list.extend(self.find_and_return_emoji_in_message(seg.data))
        return emoji_base64_list

class ListEmojiCommand(BaseCommand):
    """列表表情包Command - 响应/emoji list命令"""

    command_name = "emoji_list"
    command_description = "列表表情包"

    # === 命令设置（必须填写）===
    command_pattern = r"^/emoji list$"  # 精确匹配 "/emoji list" 命令

    async def execute(self) -> Tuple[bool, str, bool]:
        """执行列表表情包"""
        import datetime

        # 获取当前时间
        time_format: str = self.get_config("time.format", "%Y-%m-%d %H:%M:%S")  # type: ignore
        now = datetime.datetime.now()
        time_str = now.strftime(time_format)

        # 发送时间信息
        message = f"⏰ 当前时间：{time_str}"
        await self.send_text(message)

        return True, f"显示了当前时间: {time_str}", True


class RandomEmojis(BaseCommand):
    command_name = "random_emojis"
    command_description = "发送多张随机表情包"
    command_pattern = r"^/random_emojis$"

    async def execute(self):
        emojis = await emoji_api.get_random(5)
        if not emojis:
            return False, "未找到表情包", False
        emoji_base64_list = []
        for emoji in emojis:
            emoji_base64_list.append(emoji[0])
        return await self.forward_images(emoji_base64_list)

    async def forward_images(self, images: List[str]):
        """
        把多张图片用合并转发的方式发给用户
        """
        success = await self.send_forward([("0", "神秘用户", [(ReplyContentType.IMAGE, img)]) for img in images])
        return (True, "已发送随机表情包", True) if success else (False, "发送随机表情包失败", False)


# ===== 插件注册 =====


@register_plugin
class EmojiManagePlugin(BasePlugin):
    """表情包管理插件 - 管理表情包"""

    # 插件基本信息
    plugin_name: str = "emoji_manage_plugin"  # 内部标识符
    enable_plugin: bool = False
    dependencies: List[str] = []  # 插件依赖列表
    python_dependencies: List[str] = []  # Python包依赖列表
    config_file_name: str = "config.toml"  # 配置文件名

    # 配置节描述
    config_section_descriptions = {"plugin": "插件基本信息", "emoji": "表情包功能配置"}

    # 配置Schema定义
    config_schema: dict = {
        "plugin": {
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            "config_version": ConfigField(type=str, default="1.0.1", description="配置文件版本"),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (RandomEmojis.get_command_info(), RandomEmojis),
            (AddEmojiCommand.get_command_info(), AddEmojiCommand),
        ]