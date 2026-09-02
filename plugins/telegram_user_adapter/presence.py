"""Telegram 在线状态管理。

## 背景：为什么原实现没用

原实现是「消息级」的：发言时上线，发完 4-15 秒后下线。
2026-09-02 实测发现它**完全无效**——服务停了 5 分钟账号仍显示在线。

根因不在这个模块，而在 Telegram 的机制：
**每次调用任意 API，服务器就把账号标记为在线 5 分钟。**

而该群入站消息中位间隔 **8.7 秒**，``mark_read`` 对每条消息都调一次
``send_read_acknowledge``。于是：

    下线定时器（4-15 秒） < 下一条入站消息（中位 8.7 秒）
    → 刚下线就被 mark_read 的 API 调用重新续期

全天 3813 次消息间隔里，只有 19 次（0.5%）超过 5 分钟，
理论可离线时长仅 2.5 小时 / 24 小时。

24 小时在线是最难辩解的机器特征：真人有睡眠、通勤、上课。
Telegram 风控看这一条就能判定 spam，不需要分析任何消息内容。

## 解耦后的职责

本模块**只负责执行**状态上报，不再自己决定何时该在线：

- :class:`~.presence_schedule.PresenceSchedule` 决定"此刻能否在线"
  以及"驻留多久"——纯函数式，可独立测试与调整。
- 本模块在每次上线前查询调度器；睡眠时段直接拒绝上线。
- 消息读取链路在发已读前也查询调度器，离线时段跳过——
  这一条是关键，否则 mark_read 会持续续期，作息表形同虚设。
"""

from __future__ import annotations

from typing import Any, Optional

import asyncio

from .presence_schedule import PresenceSchedule


class PresenceManager:
    """按作息表上线 / 自动下线的在线状态管理器。"""

    def __init__(
        self,
        tg_client: Any,
        logger: Any,
        *,
        schedule: Optional[PresenceSchedule] = None,
    ) -> None:
        """初始化在线状态管理器。

        Args:
            tg_client: 已连接的 :class:`TelegramUserClient`。
            logger: 插件日志器。
            schedule: 作息调度器。``None`` 时使用默认作息（夜间离线）。
        """

        self._tg = tg_client
        self._logger = logger
        self._schedule = schedule if schedule is not None else PresenceSchedule()
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

    def linger_seconds(self) -> float:
        """返回本次会话结束后的驻留秒数。

        Returns:
            float: 驻留秒数，由作息调度器给出。
        """

        return self._schedule.session_linger_seconds()

    def allows_read_receipt(self) -> bool:
        """判断此刻是否允许发送已读回执。

        消息读取链路必须在调用 ``mark_read`` 前查询本方法。
        每个已读回执都是一次 API 调用，会把在线状态续期 5 分钟——
        睡眠时段若照常发已读，账号就会"边睡边在线"。

        Returns:
            bool: 允许发已读返回 ``True``。
        """

        return self._schedule.allows_read_receipt()

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
        """进入在线状态，并取消待执行的下线任务。

        睡眠时段直接拒绝——这是与原实现最大的区别。
        原来只要发言就无条件上线，作息表因此毫无约束力。

        与 ``_transition_offline`` 同样把网络 IO 放在锁外，
        避免代理抖动时拖住其他状态调用。
        """

        if not self._schedule.allows_online():
            # 作息表说现在该睡觉：不上线，也不取消已有的下线任务。
            self._logger.debug("作息表禁止此刻上线，跳过")
            return

        async with self._lock:
            self._cancel_offline_task()
            if self._online:
                return
            # 先占住状态再放锁，避免并发重复上报
            self._online = True

        if await self._set_status(offline=False):
            self._logger.debug("Telegram 账号已上线")
            return

        # 上报失败：回滚，否则会误以为在线而跳过后续上线
        async with self._lock:
            self._online = False

    async def schedule_offline(self) -> None:
        """安排一次延迟下线。

        重复调用会重置计时，因此连续发送不会中途下线。
        驻留时长由作息调度器给出（分钟级），
        原来的 4-15 秒会被下一条入站消息的 API 调用立刻覆盖。
        """

        async with self._lock:
            self._cancel_offline_task()
            if not self._online:
                return
            delay = self._schedule.session_linger_seconds()
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

        await self._transition_offline()

    async def _transition_offline(self) -> bool:
        """把状态切到离线。

        网络 IO 放在锁外：``_set_status`` 要走 Telegram API，
        代理抖动时可能耗时数秒。实测若在锁内 await，
        ``force_offline`` 会被拖住同样时长——插件 shutdown 因此卡顿。

        做法是在锁内只做"抢占"（把 ``_online`` 置 False，谁抢到谁负责
        上报），锁外再发请求。上报失败则回滚标记，让后续调用重试。

        Returns:
            bool: 本次调用真正执行了下线上报时返回 ``True``。
        """

        async with self._lock:
            self._cancel_offline_task()
            if not self._online:
                return False
            # 先占住状态再放锁，避免并发重复上报
            self._online = False

        if await self._set_status(offline=True):
            self._logger.debug("Telegram 账号已下线")
            return True

        # 上报失败：回滚标记，下次巡检会重试
        async with self._lock:
            self._online = True
        return False

    def _cancel_offline_task(self) -> None:
        """取消待执行的下线任务。"""

        task = self._offline_task
        self._offline_task = None
        if task is not None and not task.done():
            task.cancel()

    async def enforce_schedule(self) -> bool:
        """按作息表校正当前状态，供周期性巡检调用。

        发送链路只在"要发言"时才触发状态变更，但作息边界
        （比如凌晨 0 点入睡）不一定正好有发言。需要一个独立的
        巡检把账号从"忘了下线"的状态里拉回来。

        Returns:
            bool: 本次调用产生了状态变更时返回 ``True``。
        """

        if self._schedule.allows_online():
            return False

        changed = await self._transition_offline()
        if changed:
            self._logger.info("作息表要求离线，已下线")
        return changed

    async def force_offline(self) -> None:
        """立即下线，用于插件停止时收尾。"""

        await self._transition_offline()
