"""在私有临时副本上运行实际画像刷新，不改生产文件，不输出聊天正文。"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    base = args.data_dir.resolve()
    spec = importlib.util.spec_from_file_location('style_snapshot_module', ROOT/'plugins/telegram_user_adapter/style_profiles.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('Style module loader unavailable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    paths = [base/'account_profile.json', *sorted((base/'transcripts').glob('chat_*.jsonl')), *sorted((base/'chats').glob('*/SKILL.md'))]
    before = {str(p.relative_to(base)): digest(p) for p in paths}
    report = {'scope': 'actual sync on private copy; no production refresh', 'profiles': []}
    with tempfile.TemporaryDirectory(prefix='maibot-style-audit-') as temp:
        target = Path(temp)
        for p in paths:
            dest = target/p.relative_to(base)
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(p, dest)
            dest.chmod(0o600)
        if any(digest(target/rel) != sha for rel, sha in before.items()):
            raise RuntimeError('Source changed during snapshot; retry explicitly')
        owner = module._load_owner_id(target)
        samples = module._collect_outbound_messages(target, owner)
        classification = {}
        for p in (target/'chats').glob('*/SKILL.md'):
            text = p.read_text(encoding='utf-8')
            front = module._FRONTMATTER.match(text)
            metadata = front.group(2) if front else ''
            disabled = bool(module.re.search(r'(?mi)^\s*style_enabled:\s*false\s*(?:#.*)?$', metadata))
            known = bool(module.re.search(r'(?m)^style_source: owner_inbound_v1\s*$', metadata))
            classification[str(p.relative_to(target))] = {
                'qualified_owner_samples': len(samples.get(p.parent.name, [])),
                'explicitly_disabled': disabled,
                'recognized_source': known,
            }
        first = module.sync_style_profiles(target)
        first_hashes = {str(p.relative_to(target)): digest(p) for p in (target/'chats').glob('*/SKILL.md')}
        module.sync_style_profiles(target)
        second_hashes = {str(p.relative_to(target)): digest(p) for p in (target/'chats').glob('*/SKILL.md')}
        report['second_refresh_byte_identical'] = first_hashes == second_hashes
        for rel, sha in sorted(first_hashes.items()):
            report['profiles'].append({'path': rel, 'existed': rel in before, 'changed': before.get(rel) != sha, 'before_sha256': before.get(rel), 'after_sha256': sha})
        report['source_classification'] = classification
        report['explicitly_disabled_preserved'] = all(first_hashes.get(rel) == before[rel] for rel, c in classification.items() if c['explicitly_disabled'])
        report['unknown_low_sample_preserved'] = all(first_hashes.get(rel) == before[rel] for rel, c in classification.items() if not c['recognized_source'] and c['qualified_owner_samples'] < 20)
        report['refresh_reported_count'] = len(first)
    report['source_files_unchanged'] = all(p.exists() and digest(p) == before[str(p.relative_to(base))] for p in paths)
    report['profile_count'] = len(report['profiles'])
    report['changed_count'] = sum(p['changed'] for p in report['profiles'])
    out = ROOT/'data/dialogue-evaluations'/('style-refresh-snapshot-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir(mode=0o700, parents=True)
    file = out/'report.json'
    with os.fdopen(os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k,v in report.items() if k not in ('profiles', 'source_classification')} | {'report': str(file)}))
    return 0 if all(report[k] for k in ('source_files_unchanged', 'second_refresh_byte_identical', 'explicitly_disabled_preserved', 'unknown_low_sample_preserved')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
