"""Telegram 真人账号适配器插件。

与官方 Bot API 适配器的区别在于：本插件使用 MTProto（Telethon）以**真人账号**
身份登录，因此在对方看来就是一个普通用户，而不是带 BOT 标记的机器人。

职责：
1. 用真人账号登录 Telegram 并监听新消息，转换为 Host 侧结构。
2. 把 Host 出站消息经**全局串行队列**发出，附带拟人化改写、打字模拟、
   按需上线等行为。
3. 记录结构化聊天日志，并根据反馈累积自我改进经验。
4. 通过 MessageGateway 装饰器注册为双工消息网关。
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Optional, cast

import asyncio
import contextlib
import time

from maibot_sdk import MaiBotPlugin, MessageGateway, PluginConfigBase

from .codecs import TelegramUserInboundCodec
from .codecs.outbound import TelegramUserOutboundCodec
from .config import TelegramUserPluginSettings
from .constants import PLATFORM_NAME, SESSION_FILE_NAME, TELEGRAM_USER_GATEWAY_NAME
from .filters import TelegramUserChatFilter
from .presence import PresenceManager
from .self_improvement import ChatOutcome, SelfImprovementStore, detect_suspicion
from .send_queue import PRIORITY_MENTION, PRIORITY_NORMAL, QuietHoursError, SendQueue
from .telegram_user_client import TelegramUserClient, is_available as telethon_is_available
from .transcript import ChatTranscriptLogger


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
        self._presence: Optional[PresenceManager] = None
        self._send_queue: Optional[SendQueue] = None
        self._transcript: Optional[ChatTranscriptLogger] = None
        self._self_improvement: Optional[SelfImprovementStore] = None
        self._run_task: Optional[asyncio.Task[None]] = None
        self._stop_requested: bool = False
        self._self_account_id: str = ""

        # chat_id -> 最近一次被 @ / 回复的时间戳，用于发送优先级。
        self._recent_mentions: Dict[str, float] = {}
        # chat_id -> 最近一条入站消息时间戳，用于统计端到端回复延迟。
        self._last_inbound_at: Dict[str, float] = {}
        # chat_id -> 我们最近发出的内容，用于自我改进反馈判定。
        self._last_outbound_text: Dict[str, str] = {}
        # chat_id -> 我们最近发言后是否已有人接话。
        self._pending_outcome: Dict[str, asyncio.Task[None]] = {}

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
        """处理 Host 出站消息，经全局串行队列以真人账号身份发送。

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
        send_queue = self._send_queue
        if outbound_codec is None or send_queue is None:
            return {"success": False, "error": "Telegram 真人账号适配器未初始化"}

        chat_id = self._resolve_outbound_chat_id(message)
        priority = self._resolve_priority(chat_id)
        enqueued_at = time.monotonic()

        async def _do_send() -> Dict[str, Any]:
            return await outbound_codec.send_outbound_message(message, route or {})

        try:
            result = await send_queue.submit(
                _do_send,
                priority=priority,
                label=chat_id or "unknown",
            )
        except QuietHoursError:
            # 静默时段：安静丢弃，绝不向聊天回显任何内容（需求 4 + 9）。
            if self._transcript is not None and chat_id:
                await self._transcript.log_event(
                    chat_id,
                    "quiet_hours_drop",
                    {"reason": "UTC+8 静默时段内不发送"},
                )
            return {"success": False, "error": "quiet_hours", "silent": True}
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - 出站异常统一转成静默失败
            self.ctx.logger.error(f"Telegram 发送失败: {exc}")
            if self._transcript is not None and chat_id:
                await self._transcript.log_event(
                    chat_id,
                    "send_error",
                    {"error": str(exc)},
                )
            # 需求 9：出错绝不向聊天回显，只返回失败让上游静默处理。
            return {"success": False, "error": str(exc), "silent": True}

        if result.get("success") and chat_id:
            await self._after_successful_send(
                chat_id=chat_id,
                message=message,
                result=result,
                enqueued_at=enqueued_at,
                priority=priority,
                outbound_codec=outbound_codec,
            )

        return result

    async def _after_successful_send(
        self,
        *,
        chat_id: str,
        message: Dict[str, Any],
        result: Dict[str, Any],
        enqueued_at: float,
        priority: int,
        outbound_codec: TelegramUserOutboundCodec,
    ) -> None:
        """发送成功后记录日志并安排效果反馈。

        Args:
            chat_id: 目标聊天 ID。
            message: 出站消息字典。
            result: 发送结果。
            enqueued_at: 入队时间戳。
            priority: 队列优先级。
            outbound_codec: 出站编解码器，用于取观测指标。
        """

        sent_text = self._extract_text_from_message(message)
        self._last_outbound_text[chat_id] = sent_text

        inbound_at = self._last_inbound_at.get(chat_id)
        reply_latency = (time.monotonic() - inbound_at) if inbound_at else None
        typing_seconds = outbound_codec.last_typing_seconds
        queue_wait = max(0.0, time.monotonic() - enqueued_at - typing_seconds)

        if self._transcript is not None:
            await self._transcript.log_outbound(
                chat_id=chat_id,
                message_id=result.get("external_message_id"),
                text=sent_text,
                original_text=outbound_codec.last_original_text or sent_text,
                queue_wait_seconds=queue_wait,
                typing_seconds=typing_seconds,
                reply_latency_seconds=reply_latency,
                priority=priority,
                humanize_rules=outbound_codec.last_humanize_rules,
            )

        # 发言后清除该群的提及标记，避免长期占用高优先级。
        self._recent_mentions.pop(chat_id, None)

        self._schedule_outcome_check(chat_id, sent_text)

    def _schedule_outcome_check(self, chat_id: str, sent_text: str) -> None:
        """安排一次"有没有人接话"的判定。

        Args:
            chat_id: 聊天 ID。
            sent_text: 我们发出的内容。
        """

        store = self._self_improvement
        if store is None or not store.enabled:
            return

        settings = self._load_settings()
        wait_seconds = settings.observability.reply_wait_seconds
        if wait_seconds <= 0:
            return

        existing = self._pending_outcome.pop(chat_id, None)
        if existing is not None and not existing.done():
            existing.cancel()

        async def _check() -> None:
            try:
                await asyncio.sleep(wait_seconds)
            except asyncio.CancelledError:
                return
            # 走到这里说明窗口内没有被入站消息取消，即无人接话。
            with contextlib.suppress(Exception):
                await store.record_outcome(
                    ChatOutcome(chat_id=chat_id, text=sent_text, got_reply=False)
                )
            self._pending_outcome.pop(chat_id, None)

        self._pending_outcome[chat_id] = asyncio.create_task(
            _check(), name=f"telegram_user_adapter.outcome.{chat_id}"
        )

    def _resolve_outbound_chat_id(self, message: Dict[str, Any]) -> str:
        """从出站消息中解析目标 chat_id（含 topic 后缀）。

        Args:
            message: 出站消息字典。

        Returns:
            str: chat_id 字符串；无法解析时返回空串。
        """

        message_info = message.get("message_info", {}) or {}
        additional = message_info.get("additional_config", {}) or {}
        group_info = message_info.get("group_info") or {}
        user_info = message_info.get("user_info") or {}

        for candidate in (
            additional.get("platform_io_target_group_id"),
            group_info.get("group_id"),
            additional.get("platform_io_target_user_id"),
            user_info.get("user_id"),
        ):
            if candidate:
                return str(candidate)
        return ""

    def _resolve_priority(self, chat_id: str) -> int:
        """按是否被 @ / 回复决定发送优先级。

        Args:
            chat_id: 目标聊天 ID。

        Returns:
            int: 优先级数值，越小越优先。
        """

        if chat_id and chat_id in self._recent_mentions:
            return PRIORITY_MENTION
        return PRIORITY_NORMAL

    @staticmethod
    def _extract_text_from_message(message: Dict[str, Any]) -> str:
        """把出站消息段中的文本拼起来。

        Args:
            message: 出站消息字典。

        Returns:
            str: 文本内容。
        """

        raw_message = message.get("raw_message")
        if not isinstance(raw_message, list):
            return ""
        parts = [
            seg.get("data", "")
            for seg in raw_message
            if isinstance(seg, dict) and seg.get("type") == "text" and isinstance(seg.get("data"), str)
        ]
        return "".join(parts)

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
        quiet = settings.quiet_hours
        observability = settings.observability

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

        # 登录后立刻置为离线，避免 Telethon 连接本身让账号显示在线（需求 10）。
        if behavior.online_only_when_chatting:
            self._presence = PresenceManager(
                self._tg_client,
                self.ctx.logger,
                linger_min=behavior.online_linger_min,
                linger_max=behavior.online_linger_max,
            )
            await self._presence.force_offline()

        self._transcript = ChatTranscriptLogger(
            self.ctx.paths.data_dir / "transcripts",
            self.ctx.logger,
            enabled=observability.enable_transcript_log,
        )
        self._self_improvement = SelfImprovementStore(
            self.ctx.paths.data_dir,
            self.ctx.logger,
            enabled=observability.enable_self_improvement,
        )
        if self._self_improvement.enabled:
            self.ctx.logger.info(
                f"自我改进文件: {self._self_improvement.soul_path} / {self._self_improvement.skill_path}"
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
            enable_humanize=behavior.enable_humanize,
            max_emoji=behavior.max_emoji_per_message,
        )
        self._outbound_codec.set_presence_manager(self._presence)

        self._send_queue = SendQueue(
            self.ctx.logger,
            quiet_start_hour=quiet.start_hour,
            quiet_end_hour=quiet.end_hour,
            enable_quiet_hours=quiet.enable,
            min_gap_seconds=behavior.min_send_gap,
            max_gap_seconds=behavior.max_send_gap,
        )
        self._send_queue.start()

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

        for task in list(self._pending_outcome.values()):
            if not task.done():
                task.cancel()
        self._pending_outcome.clear()

        with contextlib.suppress(Exception):
            await self.ctx.gateway.update_state(
                gateway_name=TELEGRAM_USER_GATEWAY_NAME,
                ready=False,
                platform=PLATFORM_NAME,
            )

        if self._send_queue is not None:
            with contextlib.suppress(Exception):
                await self._send_queue.stop()
            self._send_queue = None

        if self._presence is not None:
            with contextlib.suppress(Exception):
                await self._presence.force_offline()
            self._presence = None

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
        self._transcript = None
        self._self_improvement = None
        self._recent_mentions.clear()
        self._last_inbound_at.clear()
        self._last_outbound_text.clear()

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

        # 用虚拟 group_id（含 topic）作为会话键，保证各群/各话题上下文隔离（需求 6）。
        session_key = self._resolve_inbound_session_key(message_dict, chat_id)
        incoming_text = message_dict.get("processed_plain_text", "") or ""
        is_mention = bool(message_dict.get("is_at"))

        self._last_inbound_at[session_key] = time.monotonic()

        if is_mention:
            # 需求 5：被 @ 或被回复时，该群下次发送享有最高优先级。
            self._recent_mentions[session_key] = time.monotonic()

        await self._record_inbound_feedback(session_key, incoming_text)

        if self._transcript is not None:
            chat = await self._safe_get_chat(event)
            await self._transcript.log_inbound(
                chat_id=session_key,
                chat_title=str(getattr(chat, "title", "") or "私聊"),
                is_private=bool(getattr(event, "is_private", False)),
                sender_id=str(sender_id),
                sender_name=str(
                    getattr(sender, "username", None) or getattr(sender, "first_name", None) or sender_id
                ),
                message_id=getattr(event.message, "id", None),
                text=incoming_text,
                is_mention=is_mention,
                has_media=getattr(event.message, "media", None) is not None,
            )

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

    async def _record_inbound_feedback(self, session_key: str, incoming_text: str) -> None:
        """把入站消息作为上一次发言的效果反馈。

        Args:
            session_key: 会话键。
            incoming_text: 对方消息文本。
        """

        store = self._self_improvement
        if store is None or not store.enabled:
            return

        our_last_text = self._last_outbound_text.get(session_key)
        if not our_last_text:
            return

        suspected = detect_suspicion(incoming_text)

        # 有人接话了，取消"冷场"判定任务。
        pending = self._pending_outcome.pop(session_key, None)
        if pending is not None and not pending.done():
            pending.cancel()

        with contextlib.suppress(Exception):
            await store.record_outcome(
                ChatOutcome(
                    chat_id=session_key,
                    text=our_last_text,
                    got_reply=True,
                    suspected=suspected,
                    suspicion_text=incoming_text if suspected else "",
                )
            )

        # 反馈只消费一次，避免同一条发言被反复计分。
        self._last_outbound_text.pop(session_key, None)

    @staticmethod
    def _resolve_inbound_session_key(message_dict: Dict[str, Any], chat_id: Any) -> str:
        """解析入站消息对应的会话键。

        Args:
            message_dict: 标准消息字典。
            chat_id: Telegram 原始 chat_id。

        Returns:
            str: 会话键（群聊为含 topic 的虚拟 group_id，私聊为对方 ID）。
        """

        message_info = message_dict.get("message_info", {}) or {}
        group_info = message_info.get("group_info") or {}
        if group_info.get("group_id"):
            return str(group_info["group_id"])

        additional = message_info.get("additional_config", {}) or {}
        if additional.get("platform_io_target_user_id"):
            return str(additional["platform_io_target_user_id"])
        return str(chat_id)

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

    async def _safe_get_chat(self, event: Any) -> Any:
        """安全获取会话实体。

        Args:
            event: Telethon 事件。

        Returns:
            Any: 会话实体；失败时返回 ``None``。
        """

        try:
            return await event.get_chat()
        except Exception:  # noqa: BLE001 - 群名解析失败不影响主流程
            return None

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
