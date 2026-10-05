"""有界事件调度。GPL-3.0；2026-10-06 修改，见 EVENTS_PORT_NOTICE.md。"""
from typing import Any, Dict, Tuple
import asyncio
import time


class EventDispatch:
    """按聊天/话题/消息隔离；typing 和编辑不能越过首次到达的硬上限。"""
    def __init__(self, deliver, *, silence=0.6, max_wait=8.0, clock=time.monotonic):
        if not 0 <= silence <= max_wait or max_wait <= 0:
            raise ValueError("无效等待上限")
        self.deliver, self.clock = deliver, clock
        self.silence, self.max_wait = silence, max_wait
        self.pending: Dict[Tuple[Any, int], list] = {}
        self.tasks: Dict[Tuple[Any, int], asyncio.Task] = {}
        self.typing_until = {}
        self.closed = False

    def submit(self, key, mid, event):
        ident = (key, mid)
        if self.closed or ident in self.tasks:
            return False
        if len(self.tasks) >= 1024:
            raise RuntimeError("事件队列已满")
        now = self.clock()
        self.pending[ident] = [event, now, now]
        task = asyncio.create_task(self._run(ident))
        self.tasks[ident] = task
        task.add_done_callback(lambda done: self._done(ident, done))
        return True

    def _done(self, ident, task):
        if self.tasks.get(ident) is task:
            self.tasks.pop(ident, None)
            self.pending.pop(ident, None)
        if not any(k[0] == ident[0] for k in self.tasks):
            self.typing_until.pop(ident[0], None)
        if not task.cancelled() and task.exception() is not None:
            asyncio.get_running_loop().call_exception_handler({
                "message": "Telegram 事件分发失败", "exception": task.exception()})

    def delay(self, key, item):
        return max(0, min(item[1] + self.max_wait,
                   max(item[2] + self.silence, self.typing_until.get(key, 0))) - self.clock())

    async def _run(self, ident):
        while not self.closed:
            item = self.pending[ident]
            delay = self.delay(ident[0], item)
            if delay <= 0:
                self.pending.pop(ident)
                await self.deliver(item[0])
                return
            await asyncio.sleep(min(delay, 0.1))

    def replace(self, key, mid, event):
        item = self.pending.get((key, mid))
        if item is None or self.closed:
            return False
        item[0], item[2] = event, self.clock()
        return True

    def typing(self, key, active):
        if not self.closed and any(k[0] == key for k in self.pending):
            self.typing_until[key] = self.clock() + 6 if active else 0

    async def cancel(self, key, mid):
        task = self.tasks.get((key, mid))
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def close(self):
        self.closed = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()
        self.pending.clear()
        self.typing_until.clear()
