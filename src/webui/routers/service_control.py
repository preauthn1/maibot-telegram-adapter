"""已认证的固定 MaiBot systemd 控制；不接受服务名或 shell 命令。"""
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request

import asyncio
import logging
import os

from src.common.runtime_loop import get_main_loop
from src.webui.dependencies import require_auth

router = APIRouter(prefix="/system/service", tags=["system"], dependencies=[Depends(require_auth)])
_lock = asyncio.Lock()
logger = logging.getLogger(__name__)


def _webui_lifecycle(main_pid: int = 0) -> Literal['coupled', 'independent']:
    """Require observed separation from the fixed core unit before enabling control."""
    if get_main_loop() is not None or os.environ.get('MAIBOT_WORKER_PROCESS') == '1':
        return 'coupled'
    try:
        cgroups = Path('/proc/self/cgroup').read_text()
        if any('maibot.service' in line.split(':', 2)[-1].split('/') for line in cgroups.splitlines()):
            return 'coupled'
        # MainPID is the runner on this deployment; the embedded worker is its child.
        pid = os.getpid()
        for _ in range(32):
            if main_pid > 0 and pid == main_pid:
                return 'coupled'
            if pid <= 1:
                return 'independent'
            stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
            pid = int(stat[1])
    except (OSError, IndexError, ValueError):
        pass
    # Unobservable topology must never authorize a destructive service action.
    return 'coupled'


def _status_metadata(main_pid: int) -> dict[str, object]:
    lifecycle = _webui_lifecycle(main_pid)
    available = os.environ.get('MAIBOT_SYSTEMD_CONTROL') == '1' and lifecycle == 'independent'
    return {
        'control_available': available,
        'control_mode': 'embedded' if lifecycle == 'coupled' else ('independent' if available else 'unavailable'),
        'webui_lifecycle': lifecycle,
        'webui_pid': os.getpid(),
    }


async def systemctl(*args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        '/usr/bin/systemctl', *args, 'maibot.service',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)
    except BaseException as exc:
        # 连接取消也必须回收子进程，不能让锁释放后遗留控制命令。
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        if isinstance(exc, asyncio.TimeoutError):
            # 4xx 而非 5xx：反向代理会替换源站错误响应体。
            raise HTTPException(408, 'systemd 操作超时，请刷新状态；操作可能仍在进行') from None
        raise
    if process.returncode:
        logger.error('MaiBot systemctl failed: %s', stderr.decode(errors='replace'))
        raise HTTPException(424, 'systemd 操作失败，请查看服务日志')
    return stdout.decode()

@router.get('')
async def service_status():
    raw = await systemctl('show', '--property=LoadState,ActiveState,SubState,MainPID,Result')
    fields = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    return {
        'unit': 'maibot.service',
        **fields,
        'running': fields.get('ActiveState') == 'active',
        **_status_metadata(int(fields.get('MainPID', '0'))),
    }

@router.post('/{action}')
async def control_service(action: Literal['start', 'stop', 'restart'], request: Request):
    if _webui_lifecycle() != 'independent':
        raise HTTPException(409, '内嵌核心或无法确认独立拓扑的 WebUI 不允许控制其所属服务')
    if os.environ.get('MAIBOT_SYSTEMD_CONTROL') != '1':
        raise HTTPException(403, '此部署未启用 systemd 控制')
    # Cookie 认证的写操作须携带同源 Origin，阻止跨站请求。
    if request.headers.get('origin') not in {'https://maibot.example.com', 'http://127.0.0.1:7999', 'http://localhost:7999', 'http://127.0.0.1:8001', 'http://localhost:8001'}:
        raise HTTPException(403, '不允许的请求来源')
    if request.headers.get('x-maibot-service-control') != '1':
        raise HTTPException(403, '缺少操作确认头')
    if _lock.locked():
        raise HTTPException(409, '已有服务操作正在执行')
    async with _lock:
        status = await service_status()
        if not status['control_available']:
            raise HTTPException(409, 'WebUI 与核心服务生命周期耦合，拒绝服务控制')
        logger.warning('Authenticated MaiBot service action=%s', action)
        await systemctl(action)
        return await service_status()
