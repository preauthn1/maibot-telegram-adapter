"""对白名单群清除通知徽标；不发消息、不发送表情、不读取私聊。"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Iterable
import asyncio
import re
import time


class ScopeRevoked(Exception):
    """等待期间目标已被移出显式白名单。"""


class ReadNotificationsWorker:
    """复用已登录的 Telethon 实例，串行执行已读及服务端回读。

    每群事件冷却 30 秒、兜底巡检 300 秒；RPC 间隔至少 2 秒。
    大积压每种至多清理三页，余下继续排队，避免抢占事件循环。
    """

    def __init__(
        self,
        client: Any,
        allowed_groups: Callable[[], Iterable[str]],
        logger: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.client = client
        self.allowed_groups = allowed_groups
        self.logger = logger
        self.clock = clock
        self.sleep = sleep
        self.status: Dict[int, Dict[str, Any]] = {}
        self._next_rpc = 0.0
        self._flood_until = 0.0
        self._next_scan: Dict[int, float] = {}
        self._cooldown: Dict[int, float] = {}
        self._dirty: set[int] = set()
        self._lock = asyncio.Lock()

    def notify(self, chat_id: int) -> None:
        """事件只合并信号，不创建逐消息任务或在回调内请求网络。"""
        if chat_id in self._groups():
            self._dirty.add(chat_id)

    def _groups(self) -> set[int]:
        # 不采用过滤器的“空白名单=所有群”语义，不修复畸形 ID 或接受用户名。
        return {int(value) for value in self.allowed_groups()
                if isinstance(value, str) and re.fullmatch(r"-[1-9][0-9]*", value)}

    async def _call(self, chat_id: int, operation: Callable[[], Awaitable[Any]]) -> Any:
        await self.sleep(max(0.0, self._next_rpc - self.clock()))
        if chat_id not in self._groups():
            raise ScopeRevoked()
        try:
            # Telethon 默认会自行等待 <=60 秒的 FloodWait；不修改共享客户端参数。
            return await asyncio.wait_for(operation(), timeout=90.0)
        finally:
            self._next_rpc = self.clock() + 2.0

    async def _clear(self, chat_id: int) -> None:
        from telethon.tl.functions.messages import GetPeerDialogsRequest, ReadMentionsRequest, ReadReactionsRequest
        from telethon.tl.types import InputDialogPeer

        peer = await self._call(chat_id, lambda: self.client.get_input_entity(chat_id))
        for request in (
            ReadReactionsRequest(peer=peer, top_msg_id=None, saved_peer_id=None),
            ReadMentionsRequest(peer=peer, top_msg_id=None),
        ):
            for _ in range(3):
                result = await self._call(chat_id, lambda request=request: self.client(request))
                if result.offset == 0:
                    break
            else:
                self._dirty.add(chat_id)
        result = await self._call(
            chat_id, lambda: self.client(GetPeerDialogsRequest(peers=[InputDialogPeer(peer=peer)]))
        )
        dialog, = result.dialogs
        self.status[chat_id] = {
            "checked_at_unix": time.time(),
            "unread_count": dialog.unread_count,
            "unread_mentions_count": dialog.unread_mentions_count,
            "unread_reactions_count": dialog.unread_reactions_count,
        }
        if dialog.unread_mentions_count or dialog.unread_reactions_count:
            self._dirty.add(chat_id)
        self.logger.info(
            f"通知已读回读: chat={chat_id} mentions={dialog.unread_mentions_count} "
            f"reactions={dialog.unread_reactions_count} unread={dialog.unread_count}"
        )

    async def tick(self) -> None:
        """单次有界巡检；FloodWait 阻止本 worker 全部请求，普通错误延迟重试。"""
        from telethon.errors import FloodPremiumWaitError, FloodTestPhoneWaitError, FloodWaitError, SlowModeWaitError

        async with self._lock:
            groups = self._groups()
            self._dirty.intersection_update(groups)
            for mapping in (self.status, self._next_scan, self._cooldown):
                for stale in set(mapping) - groups:
                    del mapping[stale]
            if self.clock() < self._flood_until:
                return
            for chat_id in sorted(groups):
                if self.clock() < self._cooldown.get(chat_id, 0):
                    continue
                if chat_id not in self._dirty and self.clock() < self._next_scan.get(chat_id, 0):
                    continue
                self._dirty.discard(chat_id)
                try:
                    await self._clear(chat_id)
                except ScopeRevoked:
                    continue
                except (FloodWaitError, FloodPremiumWaitError, FloodTestPhoneWaitError, SlowModeWaitError) as exc:
                    self._flood_until = self.clock() + max(1, exc.seconds)
                    self._dirty.add(chat_id)
                    self.status[chat_id] = {"error": type(exc).__name__, "retry_after_seconds": exc.seconds}
                    self.logger.warning(f"通知已读限流: chat={chat_id} 等待={exc.seconds}s")
                    return
                except Exception as exc:
                    # 不吞掉故障：显式记录类别；不输出异常载荷中的账号信息。
                    self.status[chat_id] = {"error": type(exc).__name__}
                    self._cooldown[chat_id] = self.clock() + 300.0
                    self.logger.warning(f"通知已读失败: chat={chat_id} error={type(exc).__name__}")
                else:
                    self._cooldown[chat_id] = self.clock() + 30.0
                self._next_scan[chat_id] = self.clock() + 300.0

    async def run(self) -> None:
        """启动即扫描历史积压，之后持续处理信号；取消直接传播到在途 RPC。"""
        while True:
            await self.tick()
            await asyncio.sleep(5.0)
