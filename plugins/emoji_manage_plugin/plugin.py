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
from src.config.config import global_config


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


class PrintMessage(BaseEventHandler):
    """打印消息事件处理器 - 处理打印消息事件"""

    event_type = EventType.ON_MESSAGE
    handler_name = "print_message_handler"
    handler_description = "打印接收到的消息"

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, str | None, None, None]:
        """执行打印消息事件处理"""
        # 打印接收到的消息
        if self.get_config("print_message.enabled", False):
            print(f"接收到消息: {message.raw_message if message else '无效消息'}")
        return True, True, "消息已打印", None, None


class ForwardMessages(BaseEventHandler):
    """
    把接收到的消息转发到指定聊天ID

    此组件是HYBRID消息和FORWARD消息的使用示例。
    每收到10条消息，就会以1%的概率使用HYBRID消息转发，否则使用FORWARD消息转发。
    """

    event_type = EventType.ON_MESSAGE
    handler_name = "forward_messages_handler"
    handler_description = "把接收到的消息转发到指定聊天ID"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.counter = 0  # 用于计数转发的消息数量
        self.messages: List[str] = []

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, None, None, None]:
        if not message:
            return True, True, None, None, None
        stream_id = message.stream_id or ""

        if message.plain_text:
            self.messages.append(message.plain_text)
            self.counter += 1
        if self.counter % 10 == 0:
            if random.random() < 0.01:
                success = await self.send_hybrid(stream_id, [(ReplyContentType.TEXT, msg) for msg in self.messages])
            else:
                success = await self.send_forward(
                    stream_id,
                    [
                        (
                            str(global_config.bot.qq_account),
                            str(global_config.bot.nickname),
                            [(ReplyContentType.TEXT, msg)],
                        )
                        for msg in self.messages
                    ],
                )
            if not success:
                raise ValueError("转发消息失败")
            self.messages = []
        return True, True, None, None, None


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
            "version": ConfigField(type=str, default="1.0.0", description="插件版本"),
            "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
        },
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (PrintMessage.get_handler_info(), PrintMessage),
            (ForwardMessages.get_handler_info(), ForwardMessages),
            (RandomEmojis.get_command_info(), RandomEmojis),
        ]


# @register_plugin
# class HelloWorldEventPlugin(BaseEPlugin):
#     """Hello World事件插件 - 处理问候和告别事件"""

#     plugin_name = "hello_world_event_plugin"
#     enable_plugin = False
#     dependencies = []
#     python_dependencies = []
#     config_file_name = "event_config.toml"

#     config_schema = {
#         "plugin": {
#             "name": ConfigField(type=str, default="hello_world_event_plugin", description="插件名称"),
#             "version": ConfigField(type=str, default="1.0.0", description="插件版本"),
#             "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
#         },
#     }

#     def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
#         return [(PrintMessage.get_handler_info(), PrintMessage)]
