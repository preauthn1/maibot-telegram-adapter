"""Telegram 真人账号适配器配置模型。"""

from __future__ import annotations

from typing import Any, ClassVar, Iterable, List, Literal

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator

from .constants import (
    DEFAULT_CHAT_LIST_TYPE,
    DEFAULT_MAX_TYPING_DELAY,
    DEFAULT_MIN_THINK_DELAY,
    DEFAULT_READ_DELAY,
    DEFAULT_TYPING_CPS,
    SUPPORTED_CONFIG_VERSION,
)


class TelegramUserPluginOptions(PluginConfigBase):
    """插件级配置。"""

    __ui_label__: ClassVar[str] = "插件设置"
    __ui_order__: ClassVar[int] = 0

    enabled: bool = Field(
        default=False,
        description="是否启用 Telegram 真人账号适配器。",
        json_schema_extra={
            "hint": "关闭后插件保持空闲，不会登录 Telegram 账号。",
            "label": "启用适配器",
            "order": 0,
        },
    )
    config_version: str = Field(
        default=SUPPORTED_CONFIG_VERSION,
        description="当前配置结构版本。",
        json_schema_extra={"disabled": True, "hidden": True, "label": "配置版本", "order": 99},
    )


class TelegramAccountConfig(PluginConfigBase):
    """Telegram 真人账号（MTProto）登录配置。"""

    __ui_label__: ClassVar[str] = "Telegram 账号"
    __ui_order__: ClassVar[int] = 1

    api_id: int = Field(
        default=0,
        description="Telegram API ID，从 https://my.telegram.org 申请。",
        json_schema_extra={"label": "API ID", "order": 0, "placeholder": "1234567"},
    )
    api_hash: str = Field(
        default="",
        description="Telegram API Hash，从 https://my.telegram.org 申请。",
        json_schema_extra={
            "input_type": "password",
            "label": "API Hash",
            "order": 1,
            "placeholder": "0123456789abcdef0123456789abcdef",
        },
    )
    session_string: str = Field(
        default="",
        description="Telethon StringSession 字符串。留空则使用插件数据目录下的会话文件。",
        json_schema_extra={
            "hint": "推荐先用 scripts/telegram_user_login.py 在本地完成登录，再把 StringSession 填到这里。",
            "input_type": "password",
            "label": "StringSession",
            "order": 2,
        },
    )
    phone: str = Field(
        default="",
        description="登录手机号（含国际区号），仅在首次交互式登录时使用。",
        json_schema_extra={"label": "手机号", "order": 3, "placeholder": "+8613800000000"},
    )
    proxy_url: str = Field(
        default="",
        description="代理地址，支持 socks5:// 与 http://。",
        json_schema_extra={
            "hint": "留空表示直连。示例：socks5://127.0.0.1:1080",
            "label": "代理地址",
            "order": 4,
            "placeholder": "socks5://127.0.0.1:1080",
        },
    )
    device_model: str = Field(
        default="iPhone 15 Pro",
        description="上报给 Telegram 的设备型号，影响“登录设备”列表中的展示。",
        json_schema_extra={"label": "设备型号", "order": 5},
    )
    system_version: str = Field(
        default="iOS 17.4",
        description="上报给 Telegram 的系统版本。",
        json_schema_extra={"label": "系统版本", "order": 6},
    )
    app_version: str = Field(
        default="10.9.1",
        description="上报给 Telegram 的客户端版本。",
        json_schema_extra={"label": "客户端版本", "order": 7},
    )

    @field_validator("api_hash", "session_string", "phone", "proxy_url", "device_model", "system_version", "app_version", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        """去掉首尾空白并统一为字符串。"""

        return "" if value is None else str(value).strip()

    @field_validator("api_id", mode="before")
    @classmethod
    def _normalize_api_id(cls, value: Any) -> int:
        """把 api_id 规范化为整数。"""

        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0


class TelegramUserBehaviorConfig(PluginConfigBase):
    """拟人化行为配置。"""

    __ui_label__: ClassVar[str] = "拟人化行为"
    __ui_order__: ClassVar[int] = 2

    simulate_typing: bool = Field(
        default=True,
        description="发送前模拟“正在输入…”状态。",
        json_schema_extra={"label": "模拟正在输入", "order": 0},
    )
    typing_chars_per_second: float = Field(
        default=DEFAULT_TYPING_CPS,
        description="模拟打字速度（字符/秒），越小越慢。",
        json_schema_extra={"label": "打字速度（字符/秒）", "order": 1},
    )
    min_think_delay: float = Field(
        default=DEFAULT_MIN_THINK_DELAY,
        description="发送前的最小停顿（秒），模拟看到消息后的反应时间。",
        json_schema_extra={"label": "最小思考停顿（秒）", "order": 2},
    )
    max_typing_delay: float = Field(
        default=DEFAULT_MAX_TYPING_DELAY,
        description="单条消息模拟打字的最长时间（秒）。",
        json_schema_extra={"label": "最长打字时间（秒）", "order": 3},
    )
    mark_read: bool = Field(
        default=True,
        description="回复前把对话标记为已读，行为更像真人。",
        json_schema_extra={"label": "自动已读", "order": 4},
    )
    read_delay: float = Field(
        default=DEFAULT_READ_DELAY,
        description="收到消息后延迟多少秒再标记已读。",
        json_schema_extra={"label": "已读延迟（秒）", "order": 5},
    )
    ignore_self_messages: bool = Field(
        default=True,
        description="忽略自己账号发出的消息，避免自我循环。",
        json_schema_extra={"label": "忽略自身消息", "order": 6},
    )
    ignore_outgoing_from_other_devices: bool = Field(
        default=True,
        description="忽略你在手机/桌面端亲自发出的消息。关闭后这些消息也会进入麦麦上下文。",
        json_schema_extra={"label": "忽略其他设备发出的消息", "order": 7},
    )
    download_media: bool = Field(
        default=True,
        description="是否下载图片/贴纸/语音等媒体供麦麦理解。",
        json_schema_extra={"label": "下载媒体", "order": 8},
    )
    max_media_size_mb: float = Field(
        default=8.0,
        description="单个媒体文件的下载大小上限（MB），超过则只保留文本占位。",
        json_schema_extra={"label": "媒体大小上限（MB）", "order": 9},
    )
    online_only_when_chatting: bool = Field(
        default=True,
        description="只在发言时上线，发完后延迟下线。关闭则始终不主动上报在线状态。",
        json_schema_extra={
            "hint": "一直挂在线是自动化最明显的特征之一。",
            "label": "仅聊天时上线",
            "order": 10,
        },
    )
    online_linger_min: float = Field(
        default=4.0,
        description="发言后保持在线的最短秒数。",
        json_schema_extra={"label": "发言后在线最短时长（秒）", "order": 11},
    )
    online_linger_max: float = Field(
        default=15.0,
        description="发言后保持在线的最长秒数。",
        json_schema_extra={"label": "发言后在线最长时长（秒）", "order": 12},
    )
    min_send_gap: float = Field(
        default=1.5,
        description="两条消息之间的最小间隔秒数（全局串行队列生效）。",
        json_schema_extra={"label": "消息最小间隔（秒）", "order": 13},
    )
    max_send_gap: float = Field(
        default=6.0,
        description="两条消息之间的最大间隔秒数。",
        json_schema_extra={"label": "消息最大间隔（秒）", "order": 14},
    )
    enable_humanize: bool = Field(
        default=True,
        description="启用中文群聊拟人化改写：去掉书面语、助手腔、markdown、多余 emoji。",
        json_schema_extra={"label": "启用拟人化改写", "order": 15},
    )
    max_emoji_per_message: int = Field(
        default=1,
        description="单条消息允许保留的 emoji 数量。",
        json_schema_extra={"label": "单条消息 emoji 上限", "order": 16},
    )
    receive_reactions: bool = Field(
        default=True,
        description="接收他人对自己消息的表情回应，作为上下文注入（不会触发回复）。让麦麦感知到\"有人给我点了❤️\"这类互动。",
        json_schema_extra={
            "hint": "只把表情回应加入上下文，不会因此主动发言。",
            "label": "接收表情回应",
            "order": 17,
        },
    )

    @field_validator(
        "typing_chars_per_second",
        "min_think_delay",
        "max_typing_delay",
        "read_delay",
        "max_media_size_mb",
        "online_linger_min",
        "online_linger_max",
        "min_send_gap",
        "max_send_gap",
        mode="before",
    )
    @classmethod
    def _normalize_float(cls, value: Any) -> float:
        """把数值字段规范化为非负浮点数。"""

        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.0
        return parsed if parsed >= 0 else 0.0

    @field_validator("max_emoji_per_message", mode="before")
    @classmethod
    def _normalize_emoji_limit(cls, value: Any) -> int:
        """把 emoji 上限规范化为非负整数。"""

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 1
        return max(0, parsed)


class TelegramUserQuietHoursConfig(PluginConfigBase):
    """静默时段配置（UTC+8）。"""

    __ui_label__: ClassVar[str] = "静默时段"
    __ui_order__: ClassVar[int] = 4

    enable: bool = Field(
        default=False,
        description="启用静默时段，期间不发送任何消息、也不处理入站消息。默认关闭：真人账号全天在线更自然，深夜也可能被 @ 后即时回应。",
        json_schema_extra={"label": "启用静默时段", "order": 0},
    )
    start_hour: int = Field(
        default=3,
        description="静默开始小时（UTC+8，含）。",
        json_schema_extra={"label": "开始小时", "order": 1},
    )
    end_hour: int = Field(
        default=7,
        description="静默结束小时（UTC+8，不含）。",
        json_schema_extra={"label": "结束小时", "order": 2},
    )

    @field_validator("start_hour", "end_hour", mode="before")
    @classmethod
    def _normalize_hour(cls, value: Any) -> int:
        """把小时规范化到 0-23。"""

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed % 24


class TelegramUserObservabilityConfig(PluginConfigBase):
    """日志与自我改进配置。"""

    __ui_label__: ClassVar[str] = "日志与自我改进"
    __ui_order__: ClassVar[int] = 5

    enable_transcript_log: bool = Field(
        default=True,
        description="记录结构化聊天日志（JSONL），用于事后审查是否像真人。",
        json_schema_extra={"label": "启用聊天记录日志", "order": 0},
    )
    enable_self_improvement: bool = Field(
        default=True,
        description="启用自我改进：把经验写入 SOUL.md 与 SKILL.md。",
        json_schema_extra={"label": "启用自我改进", "order": 1},
    )
    reply_wait_seconds: float = Field(
        default=180.0,
        description="发言后等待多少秒判定有没有人接话。",
        json_schema_extra={"label": "接话判定窗口（秒）", "order": 2},
    )

    @field_validator("reply_wait_seconds", mode="before")
    @classmethod
    def _normalize_wait(cls, value: Any) -> float:
        """把等待窗口规范化为非负浮点数。"""

        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 180.0
        return parsed if parsed >= 0 else 180.0


class TelegramUserChatConfig(PluginConfigBase):
    """聊天名单配置。"""

    __ui_label__: ClassVar[str] = "聊天过滤"
    __ui_order__: ClassVar[int] = 3

    enable_group_chat: bool = Field(
        default=True,
        description="是否参与群聊。关闭后只处理私聊，忽略所有群消息。",
        json_schema_extra={
            "hint": "关闭后即使 group_list 填了群号也不会参与群聊。",
            "label": "参与群聊",
            "order": 0,
        },
    )
    group_list_type: Literal["whitelist", "blacklist"] = Field(
        default=DEFAULT_CHAT_LIST_TYPE,
        description="群聊名单模式。",
        json_schema_extra={"label": "群聊名单模式", "order": 1},
    )
    group_list: List[str] = Field(
        default_factory=list,
        description="群聊名单中的 chat_id 列表。白名单模式下留空表示所有群。",
        json_schema_extra={"label": "群聊名单", "order": 2, "placeholder": "请输入 chat_id"},
    )
    private_list_type: Literal["whitelist", "blacklist"] = Field(
        default=DEFAULT_CHAT_LIST_TYPE,
        description="私聊名单模式。",
        json_schema_extra={"label": "私聊名单模式", "order": 3},
    )
    private_list: List[str] = Field(
        default_factory=list,
        description="私聊名单中的用户 ID 列表。",
        json_schema_extra={"label": "私聊名单", "order": 4, "placeholder": "请输入用户 ID"},
    )
    ban_user_id: List[str] = Field(
        default_factory=list,
        description="全局屏蔽的用户 ID 列表。",
        json_schema_extra={"label": "全局屏蔽用户", "order": 5, "placeholder": "请输入用户 ID"},
    )
    ignore_bots: bool = Field(
        default=True,
        description="忽略其他机器人发来的消息。",
        json_schema_extra={"label": "忽略机器人消息", "order": 6},
    )
    ignore_channels: bool = Field(
        default=True,
        description="忽略频道（channel）广播消息。",
        json_schema_extra={"label": "忽略频道消息", "order": 7},
    )

    @field_validator("group_list_type", "private_list_type", mode="before")
    @classmethod
    def _normalize_list_type(cls, value: Any) -> str:
        """规范化名单模式取值。"""

        normalized = str(value or "").strip().lower()
        return normalized if normalized in ("whitelist", "blacklist") else DEFAULT_CHAT_LIST_TYPE

    @field_validator("group_list", "private_list", "ban_user_id", mode="before")
    @classmethod
    def _normalize_id_lists(cls, value: Any) -> List[str]:
        """把名单字段规范化为去重后的字符串列表。"""

        if value is None:
            return []
        if isinstance(value, str):
            raw_items: Iterable[Any] = value.replace("\n", ",").split(",")
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
            raw_items = value
        else:
            raw_items = (value,)

        seen: set[str] = set()
        result: List[str] = []
        for item in raw_items:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                result.append(text)
        return result


class TelegramUserPluginSettings(PluginConfigBase):
    """Telegram 真人账号适配器完整配置。"""

    plugin: TelegramUserPluginOptions = Field(default_factory=TelegramUserPluginOptions)
    telegram_account: TelegramAccountConfig = Field(default_factory=TelegramAccountConfig)
    behavior: TelegramUserBehaviorConfig = Field(default_factory=TelegramUserBehaviorConfig)
    quiet_hours: TelegramUserQuietHoursConfig = Field(default_factory=TelegramUserQuietHoursConfig)
    observability: TelegramUserObservabilityConfig = Field(
        default_factory=TelegramUserObservabilityConfig
    )
    chat: TelegramUserChatConfig = Field(default_factory=TelegramUserChatConfig)

    def should_connect(self) -> bool:
        """判断当前配置是否要求建立连接。"""

        return self.plugin.enabled

    def validate_runtime_config(self, logger: Any) -> bool:
        """校验运行所需的最小配置是否齐备。

        Args:
            logger: 插件日志器。

        Returns:
            bool: 配置是否足以启动。
        """

        account = self.telegram_account
        if account.api_id <= 0 or not account.api_hash:
            logger.warning("Telegram 真人账号适配器已启用，但 api_id / api_hash 未配置")
            return False
        if not account.session_string and not account.phone:
            logger.warning(
                "Telegram 真人账号适配器缺少登录凭据：请填写 session_string，"
                "或先用 scripts/telegram_user_login.py 生成会话文件"
            )
        return True
