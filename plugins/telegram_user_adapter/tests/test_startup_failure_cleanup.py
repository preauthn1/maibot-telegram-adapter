"""执行真实关闭函数体，隔离外部资源；不导入有启动副作用的 bot.py。"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest


@pytest.mark.parametrize('plugin_stop_fails', [False, True])
def test_shutdown_continues_and_awaits_remaining_tasks(monkeypatch, plugin_stop_fails):
    source = Path(__file__).resolve().parents[3] / 'bot.py'
    tree = ast.parse(source.read_text())
    names = {'graceful_shutdown', '_await_shutdown_step'}
    nodes: list[ast.stmt] = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
    assert len(nodes) == 2
    # 保持真实函数控制流，只替换资源端点。
    import src.plugin_runtime.integration as integration
    from src.core.event_bus import event_bus
    stop = AsyncMock(side_effect=OSError('synthetic-stop') if plugin_stop_fails else None)
    monkeypatch.setattr(integration, 'get_plugin_runtime_manager', lambda: SimpleNamespace(stop=stop))
    emit = AsyncMock()
    monkeypatch.setattr(event_bus, 'emit', emit)
    manager = SimpleNamespace(stop_and_wait_all_tasks=AsyncMock())
    namespace = {'asyncio': asyncio, 'MainSystem': object, 'logger': Mock(),
                 'request_shutdown': Mock(), 't': lambda *a, **k: a[0],
                 'tn': lambda *a, **k: a[0], 'async_task_manager': manager}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)

    async def run():
        finalized = asyncio.Event()
        async def background():
            try:
                await asyncio.Event().wait()
            finally:
                finalized.set()
        task = asyncio.create_task(background())
        await asyncio.sleep(0)
        ui = SimpleNamespace(shutdown=AsyncMock())
        await namespace['graceful_shutdown'](SimpleNamespace(webui_server=ui))
        assert task.done() and task.cancelled() and finalized.is_set()
        ui.shutdown.assert_awaited_once()
    asyncio.run(run())
    stop.assert_awaited_once()
    emit.assert_awaited_once()
    manager.stop_and_wait_all_tasks.assert_awaited_once()
