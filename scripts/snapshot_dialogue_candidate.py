"""保存候选代码（含未跟踪文件），逐成员校验；不包含凭据或运行数据。"""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.umask(0o077)
    destination = Path('/root/backups/maibot-candidates') / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    destination.mkdir(parents=True, mode=0o700)
    paths = set()
    for directory in ('src', 'prompts', 'plugins/telegram_user_adapter', 'scripts', 'tests'):
        for path in (ROOT / directory).rglob('*'):
            if path.is_symlink() or not path.is_file() or '__pycache__' in path.parts:
                continue
            if path.suffix in ('.py', '.prompt'):
                paths.add(path)
    # 测试样本独立限定目录，避免把运行配置/聊天数据按JSON后缀误打包。
    for directory in ('tests', 'plugins/telegram_user_adapter/tests'):
        for path in (ROOT / directory).rglob('*.json'):
            if path.is_symlink() or not path.is_file() or '__pycache__' in path.parts:
                continue
            json.loads(path.read_text(encoding='utf-8'))
            paths.add(path)
    for name in ('bot.py', 'pyproject.toml', 'requirements.txt', 'uv.lock'):
        path = ROOT / name
        if path.is_file() and not path.is_symlink():
            paths.add(path)
    hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    archive = destination / 'candidate.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        for relative in hashes:
            bundle.add(ROOT / relative, arcname=relative, recursive=False)
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if len(members) != len(hashes) or {m.name for m in members} != set(hashes):
            raise RuntimeError('Archive manifest mismatch')
        for member in members:
            handle = bundle.extractfile(member)
            if handle is None or hashlib.sha256(handle.read()).hexdigest() != hashes[member.name]:
                raise RuntimeError('Archive content mismatch')
    if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha for name, sha in hashes.items()):
        raise RuntimeError('Source changed during snapshot')
    required = 'plugins/telegram_user_adapter/scoped_experience_export.py'
    if required not in hashes:
        raise RuntimeError('Required untracked runtime file missing')
    manifest = {'scope': 'candidate code snapshot; not known-good running-version rollback or complete deployment backup',
                'head': subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip(),
                'files': hashes, 'file_count': len(hashes), 'verified': True,
                'excluded': ['credentials/configuration', 'databases', 'chat profiles', 'transcripts', 'virtualenv', 'other plugins', 'systemd units'],
                'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'directory': str(destination), 'file_count': len(hashes), 'archive_bytes': archive.stat().st_size, 'verified': True, 'required_runtime_file_included': True}))


if __name__ == '__main__':
    main()
