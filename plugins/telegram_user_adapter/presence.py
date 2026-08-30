"""Telegram 在线状态管理。

Telethon 默认**不会**自动上报在线状态，因此账号的"上线"完全由我们控制。

真人的在线状态是**间歇性**的：打开 app 看一眼、回几条消息、然后放下手机。
一直挂着"在线"是自动化最明显的特征之一。

本模块实现：
- 只在真正要发言时才上线；
- 发完后延迟一小段时间再下线（模拟"发完还看了会儿"）；
- 任何时刻只有一个下线定时器，避免并发发送时反复上下线抖动。
"""

from __future__ import annotations

from typing import Any, Optional

import asyncio
import random


class PresenceManager:
    """按需上线 / 自动下线的在线状态管理器。"""

    def __init__(
        self,
        tg_client: Any,
        logger: Any,
        *,
        linger_min: float = 4.0,
        linger_max: float = 15.0,
    ) -> None:
        """初始化在线状态管理器。

        Args:
            tg_client: 已连接的 :class:`TelegramUserClient`。
            logger: 插件日志器。
            linger_min: 发言后保持在线的最短秒数。
            linger_max: 发言后保持在线的最长秒数。
        """

        self._tg = tg_client
        self._logger = logger
        self._linger_min = linger_min
        self._linger_max = linger_max
        self._online = False
        self._offline_task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()

    @property
    def is_online(self) -> bool:
        """返回当前是否处于在线状态。

        Returns:
            bool: 在线返回 ``True``。
        """

        return self._online

    async def _set_status(self, *, offline: bool) -> bool:
        """向 Telegram 上报在线状态。

        Args:
            offline: ``True`` 表示离线，``False`` 表示在线。

        Returns:
            bool: 上报成功返回 ``True``。
        """

        client = getattr(self._tg, "client", None)
        if client is None:
            return False

        try:
            from telethon.tl.functions.account import UpdateStatusRequest

            await client(UpdateStatusRequest(offline=offline))
            return True
        except Exception as exc:  # noqa: BLE001 - 状态上报失败不应中断发送
            self._logger.debug(f"上报在线状态失败(offline={offline}): {exc}")
            return False

    async def go_online(self) -> None:
        """进入在线状态，并取消待执行的下线任务。"""

        async with self._lock:
            self._cancel_offline_task()
            if self._online:
                return
            if await self._set_status(offline=False):
                self._online = True
                self._logger.debug("Telegram 账号已上线")

    async def schedule_offline(self) -> None:
        """安排一次延迟下线。

        重复调用会重置计时，因此连续发送不会中途下线。
        """

        async with self._lock:
            self._cancel_offline_task()
            if not self._online:
                return
            delay = random.uniform(self._linger_min, self._linger_max)
            self._offline_task = asyncio.create_task(
                self._offline_after(delay),
                name="telegram_user_adapter.presence_offline",
            )

    async def _offline_after(self, delay: float) -> None:
        """等待指定秒数后下线。

        Args:
            delay: 等待秒数。
        """

        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        async with self._lock:
            if not self._online:
                return
            if await self._set_status(offline=True):
                self._online = False
                self._logger.debug("Telegram 账号已下线")

    def _cancel_offline_task(self) -> None:
        """取消待执行的下线任务。"""

        task = self._offline_task
        self._offline_task = None
        if task is not None and not task.done():
            task.cancel()

    async def force_offline(self) -> None:
        """立即下线，用于插件停止时收尾。"""

        async with self._lock:
            self._cancel_offline_task()
            if not self._online:
                return
            await self._set_status(offline=True)
            self._online = False
            self._logger.debug("Telegram 账号已强制下线")
