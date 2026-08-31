"""发送队列的故障恢复测试。

审计发现 SendQueue 的 worker 一旦非正常退出（宿主 TaskGroup 收尾、
取消传播、action 内抛 CancelledError），`_running` 不会复位：

- ``start()`` 因幂等守卫拒绝重建 worker
- ``submit()`` 因 `_running` 仍为 True 而放行，heappush 后
  ``await future`` **永久挂起**，没有超时、没有日志

结果是整条出站通道死锁，账号表现为"彻底哑掉"——而这种哑掉
本身也是异常信号。
"""

from pathlib import Path

import asyncio
import logging
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from telegram_user_adapter.send_queue import SendQueue  # noqa: E402

def test_worker_cancel_resets_running_flag() -> None:
    """worker 被取消后必须复位 _running，否则出站通道永久死锁。

    审计发现的 P1：_run() 的三条异常出口都直接结束协程，不复位
    _running。此后 start() 因幂等守卫拒绝重建 worker，而 submit()
    因 _running 仍为 True 而放行，heappush 后 await future 永久挂起
    ——没有超时、没有日志，账号表现为"彻底哑掉"。
    """

    async def scenario() -> None:
        queue = SendQueue(logging.getLogger("test"), enable_quiet_hours=False)
        queue.start()
        # 让 worker 真正进入循环体，否则取消发生在协程启动之前
        await asyncio.sleep(0.05)

        # 模拟宿主 TaskGroup 收尾等场景下的非正常取消
        queue._worker.cancel()
        await asyncio.sleep(0.05)

        assert queue._running is False, (
            "worker 已死但 _running 仍为 True："
            "start() 会拒绝重启，submit() 会永久挂起"
        )

    asyncio.run(scenario())


def test_pending_futures_fail_fast_on_worker_death() -> None:
    """worker 死亡时，堆里等待的任务要立刻拿到异常而不是永久等待。

    按 AGENTS.md「错误要及时完整暴露」，不应静默挂起。
    """

    async def scenario() -> None:
        queue = SendQueue(
            logging.getLogger("test"),
            enable_quiet_hours=False,
            min_gap_seconds=10.0,
            max_gap_seconds=10.0,
        )
        queue.start()
        await asyncio.sleep(0.05)

        async def slow() -> str:
            await asyncio.sleep(5)
            return "done"

        # 先塞一个正在执行的任务，再塞一个排队的
        first = asyncio.create_task(queue.submit(slow, label="chat-a"))
        await asyncio.sleep(0.05)
        second = asyncio.create_task(queue.submit(slow, label="chat-b"))
        await asyncio.sleep(0.05)

        queue._worker.cancel()
        await asyncio.sleep(0.05)

        # 排队中的那个应当很快以异常结束，而不是挂到天荒地老
        try:
            await asyncio.wait_for(second, timeout=1.0)
        except asyncio.TimeoutError:
            raise AssertionError("worker 死后排队任务仍在永久等待") from None
        except RuntimeError as exc:
            # _drain_pending 设置的异常，说明错误被及时暴露了
            assert "worker" in str(exc)
        except asyncio.CancelledError:
            pass  # 也是可接受的终态：调用方立刻知道任务没发出

        first.cancel()

    asyncio.run(scenario())
