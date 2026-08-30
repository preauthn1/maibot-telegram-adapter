"""Telegram 真人账号适配器插件。

与官方 Bot API 适配器的区别在于：本插件使用 MTProto（Telethon）以**真人账号**
身份登录，因此在对方看来就是一个普通用户，而不是带 BOT 标记的机器人。

职责：
1. 用真人账号登录 Telegram 并监听新消息，转换为 Host 侧结构。
2. 把 Host 出站消息转换为 Telethon 调用，并附带已读 / 正在输入等拟人化行为。
3. 通过 MessageGateway 装饰器注册为双工消息网关。
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Optional, cast

import asyncio
import contextlib

from maibot_sdk import MaiBotPlugin, MessageGateway, PluginConfigBase

from .codecs import TelegramUserInboundCodec
from .codecs.outbound import TelegramUserOutboundCodec
from .config import TelegramUserPluginSettings
from .constants import PLATFORM_NAME, SESSION_FILE_NAME, TELEGRAM_USER_GATEWAY_NAME
from .filters import TelegramUserChatFilter
from .telegram_user_client import TelegramUserClient, is_available as telethon_is_available


class TelegramUserAdapterPlugin(MaiBotPlugin):
    """Telegram 真人账号消息网关插件。"""

    config_model: ClassVar[type[PluginConfigBase] | None] = TelegramUserPluginSettings

    def __init__(self) -> None:
        """初始化插件运行时状态。"""

        super().__init__()
        self._tg_client: Optional[TelegramUserClient] = None
        self._inbound_codec: Optional[TelegramUserInboundCodec] = None
        self._outbound_codec: Optional[TelegramUserOutboundCodec] = None
        self._chat_filter: Optional[TelegramUserChatFilter] = None
        self._run_task: Optional[asyncio.Task[None]] = None
        self._stop_requested: bool = False
        self._self_account_id: str = ""

    async def on_load(self) -> None:
        """插件加载时根据配置决定是否登录。"""

        await self._restart_if_needed()

    async def on_unload(self) -> None:
        """插件卸载时断开连接。"""

        await self._stop_client()

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        """配置更新后重建连接。

        Args:
            scope: 配置作用域。
            config_data: 新的配置数据。
            version: 配置版本。
        """

        del version
        if scope != "self":
            return
        self.set_plugin_config(config_data)
        await self._restart_if_needed()

    @MessageGateway(
        name=TELEGRAM_USER_GATEWAY_NAME,
        route_type="duplex",
        platform=PLATFORM_NAME,
        protocol="telegram_mtproto_user",
        description="Telegram 真人账号双工消息网关（MTProto / Telethon）",
    )
    async def handle_telegram_user_gateway(
        self,
        message: Dict[str, Any],
        route: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """处理 Host 出站消息并以真人账号身份发送。

        Args:
            message: 出站标准消息字典。
            route: Platform IO 路由信息。
            metadata: 附加元数据。
            **kwargs: 兼容占位参数。

        Returns:
            Dict[str, Any]: 标准化发送结果。
        """

        del metadata, kwargs

        outbound_codec = self._outbound_codec
        if outbound_codec is None:
            return {"success": False, "error": "Telegram 真人账号适配器未初始化"}

        try:
            return await outbound_codec.send_outbound_message(message, route or {})
        except Exception as exc:  # noqa: BLE001 - 出站异常统一转成失败回执
            return {"success": False, "error": str(exc)}

    def _load_settings(self) -> TelegramUserPluginSettings:
        """读取当前插件配置。

        Returns:
            TelegramUserPluginSettings: 强类型配置对象。
        """

        return cast(TelegramUserPluginSettings, self.config)

    async def _restart_if_needed(self) -> None:
        """按当前配置重建 Telegram 连接。"""

        settings = self._load_settings()
        await self._stop_client()

        if not settings.should_connect():
            self.ctx.logger.info("Telegram 真人账号适配器保持空闲状态，因为插件未启用")
            return
        if not settings.validate_runtime_config(self.ctx.logger):
            return
        if not telethon_is_available():
            self.ctx.logger.error(
                "Telegram 真人账号适配器依赖 telethon，请先安装：uv pip install telethon cryptg"
            )
            return

        account = settings.telegram_account
        behavior = settings.behavior

        self._tg_client = TelegramUserClient(
            api_id=account.api_id,
            api_hash=account.api_hash,
            session_string=account.session_string,
            session_path=self.ctx.paths.data_dir / SESSION_FILE_NAME,
            proxy_url=account.proxy_url,
            device_model=account.device_model,
            system_version=account.system_version,
            app_version=account.app_version,
            logger=self.ctx.logger,
        )

        try:
            connected = await self._tg_client.connect()
        except Exception as exc:  # noqa: BLE001 - 登录失败必须完整暴露原因
            self.ctx.logger.error(f"Telegram 真人账号登录失败: {exc}")
            await self._stop_client()
            return

        if not connected:
            await self._stop_client()
            return

        me = self._tg_client.me
        self_id = int(getattr(me, "id", 0) or 0)
        self_username = getattr(me, "username", None)
        if self_id <= 0:
            self.ctx.logger.error("无法获取 Telegram 账号身份，适配器不会启动监听")
            await self._stop_client()
            return

        self._self_account_id = str(self_id)
        self.ctx.logger.info(
            f"Telegram 真人账号已登录: id={self_id}, username={self_username}, "
            f"phone={getattr(me, 'phone', None)}"
        )

        self._inbound_codec = TelegramUserInboundCodec(self._tg_client, self.ctx.logger)
        self._inbound_codec.set_self(self_id, self_username)
        self._inbound_codec.set_media_policy(
            download_media=behavior.download_media,
            max_media_bytes=int(behavior.max_media_size_mb * 1024 * 1024),
        )

        self._outbound_codec = TelegramUserOutboundCodec(self._tg_client, self.ctx.logger)
        self._outbound_codec.set_behavior(
            simulate_typing=behavior.simulate_typing,
            typing_cps=behavior.typing_chars_per_second,
            min_think_delay=behavior.min_think_delay,
            max_typing_delay=behavior.max_typing_delay,
        )

        self._chat_filter = TelegramUserChatFilter(self.ctx.logger)

        self._tg_client.add_message_handler(
            self._on_new_message,
            incoming_only=behavior.ignore_outgoing_from_other_devices,
        )

        await self.ctx.gateway.update_state(
            gateway_name=TELEGRAM_USER_GATEWAY_NAME,
            ready=True,
            platform=PLATFORM_NAME,
            account_id=self._self_account_id,
        )

        self._stop_requested = False
        self._run_task = asyncio.create_task(self._run_loop(), name="telegram_user_adapter.run")

    async def _stop_client(self) -> None:
        """停止监听并释放 Telegram 连接。"""

        self._stop_requested = True

        with contextlib.suppress(Exception):
            await self.ctx.gateway.update_state(
                gateway_name=TELEGRAM_USER_GATEWAY_NAME,
                ready=False,
                platform=PLATFORM_NAME,
            )

        run_task = self._run_task
        self._run_task = None
        if run_task is not None:
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_task

        if self._tg_client is not None:
            with contextlib.suppress(Exception):
                await self._tg_client.close()
            self._tg_client = None

        self._inbound_codec = None
        self._outbound_codec = None
        self._chat_filter = None

    async def _run_loop(self) -> None:
        """保持 Telethon 事件循环运行直到断开。"""

        tg_client = self._tg_client
        if tg_client is None:
            return

        self.ctx.logger.info("Telegram 真人账号适配器开始监听消息...")
        try:
            await tg_client.run_until_disconnected()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 事件循环异常需要完整记录
            self.ctx.logger.error(f"Telegram 监听循环异常退出: {exc}")

    async def _on_new_message(self, event: Any) -> None:
        """处理一条 Telethon 新消息事件。

        Args:
            event: Telethon ``NewMessage.Event``。
        """

        settings = self._load_settings()
        behavior = settings.behavior

        inbound_codec = self._inbound_codec
        chat_filter = self._chat_filter
        tg_client = self._tg_client
        if inbound_codec is None or chat_filter is None or tg_client is None:
            return

        sender_id = getattr(event, "sender_id", None)
        chat_id = getattr(event, "chat_id", None)
        if sender_id is None or chat_id is None:
            return

        if behavior.ignore_self_messages and str(sender_id) == self._self_account_id:
            return

        sender = None
        with contextlib.suppress(Exception):
            sender = await event.get_sender()

        allowed = chat_filter.check_allow(
            settings.chat,
            user_id=str(sender_id),
            chat_id=str(chat_id),
            is_private=bool(getattr(event, "is_private", False)),
            is_channel=bool(getattr(event, "is_channel", False)) and not bool(getattr(event, "is_group", False)),
            sender_is_bot=bool(getattr(sender, "bot", False)),
        )
        if not allowed:
            return

        if behavior.mark_read:
            if behavior.read_delay > 0:
                await asyncio.sleep(behavior.read_delay)
            await tg_client.mark_read(await self._resolve_read_entity(event), getattr(event.message, "id", None))

        try:
            message_dict = await inbound_codec.build_message_dict(event)
        except Exception as exc:  # noqa: BLE001 - 转换失败需要暴露具体消息
            self.ctx.logger.error(f"Telegram 消息转换失败: {exc}")
            return

        if message_dict is None:
            return

        external_message_id = f"{chat_id}:{getattr(event.message, 'id', '')}"
        try:
            await self.ctx.gateway.route_message(
                gateway_name=TELEGRAM_USER_GATEWAY_NAME,
                message=message_dict,
                route_metadata=self._build_route_metadata(),
                external_message_id=external_message_id,
                dedupe_key=external_message_id,
            )
        except Exception as exc:  # noqa: BLE001 - 路由失败需要暴露具体消息
            self.ctx.logger.error(f"Telegram 消息路由到 Host 失败: {exc}")

    async def _resolve_read_entity(self, event: Any) -> Any:
        """解析用于标记已读的会话实体。

        Args:
            event: Telethon 事件。

        Returns:
            Any: 会话实体；解析失败时回退为 chat_id。
        """

        try:
            return await event.get_chat()
        except Exception:  # noqa: BLE001 - 解析失败回退裸 ID
            return event.chat_id

    def _build_route_metadata(self) -> Dict[str, Any]:
        """构造注入 Host 时的路由辅助信息。

        Returns:
            Dict[str, Any]: 路由元数据。
        """

        if not self._self_account_id:
            return {}
        return {
            "self_id": self._self_account_id,
            "platform_io_account_id": self._self_account_id,
        }


def create_plugin() -> TelegramUserAdapterPlugin:
    """创建插件实例。

    Returns:
        TelegramUserAdapterPlugin: 插件实例。
    """

    return TelegramUserAdapterPlugin()
