"""Telethon 真人账号客户端封装。

把 Telethon 的连接、登录、拟人化动作（已读、正在输入）与媒体下载封装成
适配器插件可直接调用的最小接口，避免把 Telethon 细节散落到编解码层。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

import asyncio


def is_available() -> bool:
    """检查运行环境是否安装了 Telethon。

    Returns:
        bool: 可导入 Telethon 时返回 ``True``。
    """

    try:
        import telethon  # noqa: F401
    except ImportError:
        return False
    return True


def _build_proxy(proxy_url: str) -> Optional[tuple]:
    """把代理 URL 转换为 Telethon 需要的 proxy 元组。

    Args:
        proxy_url: ``socks5://host:port`` 或 ``http://host:port``，
            也支持带用户名密码的形式。

    Returns:
        Optional[tuple]: Telethon 的 proxy 参数；无代理时返回 ``None``。

    Raises:
        ValueError: 当代理协议不受支持或地址无法解析时抛出。
    """

    normalized = str(proxy_url or "").strip()
    if not normalized:
        return None

    import socks
    from urllib.parse import urlparse

    parsed = urlparse(normalized)
    scheme = (parsed.scheme or "").lower()
    proxy_types = {
        "socks5": socks.SOCKS5,
        "socks5h": socks.SOCKS5,
        "socks4": socks.SOCKS4,
        "http": socks.HTTP,
        "https": socks.HTTP,
    }
    proxy_type = proxy_types.get(scheme)
    if proxy_type is None:
        raise ValueError(f"不支持的代理协议: {scheme or normalized}")
    if not parsed.hostname or not parsed.port:
        raise ValueError(f"代理地址缺少主机或端口: {normalized}")

    if parsed.username:
        return (proxy_type, parsed.hostname, parsed.port, True, parsed.username, parsed.password or "")
    return (proxy_type, parsed.hostname, parsed.port)


class TelegramUserClient:
    """基于 Telethon MTProto 的真人账号客户端。"""

    def __init__(
        self,
        *,
        api_id: int,
        api_hash: str,
        session_string: str,
        session_path: Path,
        proxy_url: str,
        device_model: str,
        system_version: str,
        app_version: str,
        logger: Any,
    ) -> None:
        """初始化客户端参数。

        Args:
            api_id: Telegram API ID。
            api_hash: Telegram API Hash。
            session_string: Telethon StringSession；为空时使用会话文件。
            session_path: 会话文件路径（session_string 为空时生效）。
            proxy_url: 代理地址；为空表示直连。
            device_model: 上报的设备型号。
            system_version: 上报的系统版本。
            app_version: 上报的客户端版本。
            logger: 插件日志器。
        """

        self._api_id = api_id
        self._api_hash = api_hash
        self._session_string = session_string
        self._session_path = session_path
        self._proxy_url = proxy_url
        self._device_model = device_model
        self._system_version = system_version
        self._app_version = app_version
        self._logger = logger
        self._client: Any = None
        self._me: Any = None

    @property
    def client(self) -> Any:
        """返回底层 Telethon 客户端实例。

        Returns:
            Any: Telethon ``TelegramClient``；尚未连接时为 ``None``。
        """

        return self._client

    @property
    def me(self) -> Any:
        """返回已登录账号的用户实体。

        Returns:
            Any: Telethon ``User``；尚未登录时为 ``None``。
        """

        return self._me

    async def connect(self) -> bool:
        """建立连接并确认已登录。

        Returns:
            bool: 已登录返回 ``True``；未授权或连接失败返回 ``False``。
        """

        from telethon import TelegramClient
        from telethon.sessions import StringSession

        proxy = _build_proxy(self._proxy_url)

        if self._session_string:
            session: Any = StringSession(self._session_string)
        else:
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            session = str(self._session_path)

        self._client = TelegramClient(
            session,
            self._api_id,
            self._api_hash,
            proxy=proxy,
            device_model=self._device_model,
            system_version=self._system_version,
            app_version=self._app_version,
        )

        await self._client.connect()
        if not await self._client.is_user_authorized():
            self._logger.error(
                "Telegram 账号尚未授权。请先运行 scripts/telegram_user_login.py 完成登录，"
                "或把生成的 StringSession 填入插件配置。"
            )
            await self.close()
            return False

        self._me = await self._client.get_me()
        return True

    async def close(self) -> None:
        """断开连接并释放资源。"""

        client = self._client
        self._client = None
        self._me = None
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception as exc:  # noqa: BLE001 - 关闭链路失败只记录
            self._logger.warning(f"断开 Telegram 连接时出错: {exc}")

    def add_message_handler(self, handler: Callable[[Any], Any], *, incoming_only: bool) -> None:
        """注册新消息事件处理器。

        Args:
            handler: 接收 Telethon ``NewMessage.Event`` 的异步回调。
            incoming_only: 为 ``True`` 时仅监听收到的消息，忽略本账号发出的消息。
        """

        from telethon import events

        if self._client is None:
            raise RuntimeError("Telegram 客户端尚未连接")

        if incoming_only:
            event_filter = events.NewMessage(incoming=True)
        else:
            event_filter = events.NewMessage()
        self._client.add_event_handler(handler, event_filter)

    async def run_until_disconnected(self) -> None:
        """阻塞直到连接断开。"""

        if self._client is None:
            raise RuntimeError("Telegram 客户端尚未连接")
        await self._client.run_until_disconnected()

    async def mark_read(self, entity: Any, message_id: Optional[int] = None) -> None:
        """把会话标记为已读。

        Args:
            entity: 目标会话实体或 ID。
            message_id: 读到的消息 ID。
        """

        if self._client is None:
            return
        try:
            if message_id is None:
                await self._client.send_read_acknowledge(entity)
            else:
                await self._client.send_read_acknowledge(entity, max_id=message_id)
        except Exception as exc:  # noqa: BLE001 - 已读失败不影响主流程
            self._logger.debug(f"标记已读失败: {exc}")

    async def simulate_typing(self, entity: Any, seconds: float) -> None:
        """在目标会话中模拟“正在输入…”。

        Args:
            entity: 目标会话实体或 ID。
            seconds: 持续时长。
        """

        if self._client is None or seconds <= 0:
            return
        try:
            async with self._client.action(entity, "typing"):
                await asyncio.sleep(seconds)
        except Exception as exc:  # noqa: BLE001 - 输入状态失败仅降级
            self._logger.debug(f"模拟输入状态失败: {exc}")
            await asyncio.sleep(seconds)

    async def send_text(
        self,
        entity: Any,
        text: str,
        *,
        reply_to: Optional[int] = None,
    ) -> Any:
        """发送文本消息。

        Args:
            entity: 目标会话实体或 ID。
            text: 文本内容。
            reply_to: 要回复的消息 ID。

        Returns:
            Any: Telethon 返回的已发送消息对象。
        """

        if self._client is None:
            raise RuntimeError("Telegram 客户端尚未连接")
        return await self._client.send_message(entity, text, reply_to=reply_to)

    async def send_file(
        self,
        entity: Any,
        data: bytes,
        *,
        file_name: str,
        reply_to: Optional[int] = None,
        force_document: bool = False,
        voice_note: bool = False,
    ) -> Any:
        """发送二进制文件（图片/语音/贴纸等）。

        Args:
            entity: 目标会话实体或 ID。
            data: 文件二进制内容。
            file_name: 文件名，Telethon 据此推断 MIME。
            reply_to: 要回复的消息 ID。
            force_document: 是否强制作为文件发送。
            voice_note: 是否作为语音条发送。

        Returns:
            Any: Telethon 返回的已发送消息对象。
        """

        if self._client is None:
            raise RuntimeError("Telegram 客户端尚未连接")

        import io

        stream = io.BytesIO(data)
        stream.name = file_name
        return await self._client.send_file(
            entity,
            stream,
            reply_to=reply_to,
            force_document=force_document,
            voice_note=voice_note,
        )

    async def download_media_bytes(self, message: Any, max_bytes: int) -> Optional[bytes]:
        """下载消息附带的媒体。

        Args:
            message: Telethon 消息对象。
            max_bytes: 大小上限；超过则跳过下载。

        Returns:
            Optional[bytes]: 媒体二进制；不下载或失败时返回 ``None``。
        """

        if self._client is None or message is None:
            return None

        size = getattr(getattr(message, "file", None), "size", None)
        if isinstance(size, int) and max_bytes > 0 and size > max_bytes:
            self._logger.debug(f"媒体体积 {size} 超过上限 {max_bytes}，跳过下载")
            return None

        try:
            return await self._client.download_media(message, file=bytes)
        except Exception as exc:  # noqa: BLE001 - 下载失败降级为文本占位
            self._logger.warning(f"下载 Telegram 媒体失败: {exc}")
            return None

    async def get_entity(self, entity_id: Any) -> Any:
        """按 ID 解析会话实体。

        Args:
            entity_id: 会话 ID 或用户名。

        Returns:
            Any: Telethon 实体对象。
        """

        if self._client is None:
            raise RuntimeError("Telegram 客户端尚未连接")
        return await self._client.get_entity(entity_id)
