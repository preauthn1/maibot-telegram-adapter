# SPDX-License-Identifier: GPL-3.0-only
# Modified 2026-10-06; see PORT_NOTICES.md.
"""独立限额进程转换动图，不让解码器占满主事件循环。"""
from pathlib import Path
from typing import Optional
import asyncio
import os
import shutil
import tempfile

# prlimit 是 Linux util-linux；不调用 shell，不接受外部路径或 URL。
_LOCK = asyncio.Lock()
MAX_INPUT = 8 * 1024 * 1024
MAX_OUTPUT = 4 * 1024 * 1024


async def bounded_gif(data: bytes) -> Optional[bytes]:
    if not data or len(data) > MAX_INPUT:
        return None
    ffmpeg, prlimit = shutil.which("ffmpeg"), shutil.which("prlimit")
    if not ffmpeg or not prlimit or _LOCK.locked():
        return None
    async with _LOCK:
        with tempfile.TemporaryDirectory(prefix="tg-fidelity-") as directory:
            src, dst = Path(directory) / "input.bin", Path(directory) / "output.gif"
            src.write_bytes(data)
            command = [prlimit, "--as=536870912", "--cpu=8", "--fsize=4194304", "--nofile=64", "--",
                       ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                       "-protocol_whitelist", "file", "-threads", "1", "-filter_threads", "1",
                       "-filter_complex_threads", "1", "-max_alloc", "67108864",
                       "-i", str(src), "-an", "-sn", "-dn", "-t", "6", "-frames:v", "12",
                       "-vf", "fps=2,scale=320:320:force_original_aspect_ratio=decrease",
                       "-threads", "1", "-f", "gif", str(dst)]
            env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
            proc = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.DEVNULL,
                                                        stderr=asyncio.subprocess.DEVNULL, env=env)
            try:
                await asyncio.wait_for(proc.wait(), 12)
            except BaseException:
                if proc.returncode is None:
                    proc.kill()
                await proc.wait()
                raise
            if proc.returncode or not dst.exists() or not 0 < dst.stat().st_size <= MAX_OUTPUT:
                return None
            result = dst.read_bytes()
            return result if result[:6] in (b"GIF87a", b"GIF89a") else None
