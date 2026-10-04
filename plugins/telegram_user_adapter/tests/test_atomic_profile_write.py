"""画像原子替换失败不得破坏旧内容。"""
import sys
from pathlib import Path
import stat
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from telegram_user_adapter import style_profiles as module


def test_success_preserves_mode(tmp_path):
    path = tmp_path / 'SKILL.md'
    path.write_text('OLD')
    path.chmod(0o640)
    module.atomic_write_profile(path, 'NEW完整正文')
    assert path.read_text() == 'NEW完整正文'
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert not list(tmp_path.glob('.style-*'))


def test_reader_observes_only_complete_versions(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    path = tmp_path / 'SKILL.md'
    versions = ['旧画像正文。' * 2000, '新画像正文。' * 2000]
    path.write_text(versions[0], encoding='utf-8')
    ready, stop = Event(), Event()
    def read_loop():
        count = 0
        try:
            while not stop.is_set():
                content = path.read_text(encoding='utf-8')
                assert content in versions
                count += 1
                ready.set()
        finally:
            ready.set()
        return count
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(read_loop)
        try:
            assert ready.wait(timeout=5)
            for index in range(100):
                module.atomic_write_profile(path, versions[index % 2])
        finally:
            stop.set()
        assert future.result(timeout=5) > 0
    assert path.read_text(encoding='utf-8') == versions[1]
    assert not list(tmp_path.glob('.style-*'))


@pytest.mark.parametrize('operation', ['fsync', 'replace'])
def test_failure_preserves_old(tmp_path, monkeypatch, operation):
    path = tmp_path / 'SKILL.md'
    path.write_text('OLD完整正文')
    def fail(*args):
        raise OSError('simulated failure')
    monkeypatch.setattr(module.os, operation, fail)
    with pytest.raises(OSError):
        module.atomic_write_profile(path, 'NEW')
    assert path.read_text() == 'OLD完整正文'
    assert not list(tmp_path.glob('.style-*'))
