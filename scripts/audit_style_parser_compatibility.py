"""只读审计生产画像与严格解析兼容性；不导入应用，不输出正文或聊天ID。"""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]


def legacy(raw):
    if not raw.startswith('---\n'):
        return {}
    end = raw.find('\n---', 4)
    if end < 0:
        return {}
    result = {}
    for line in raw[4:end].splitlines():
        key, sep, value = line.partition(':')
        if sep:
            result[key.strip()] = value.strip()
    return result


def main():
    os.umask(0o077)
    source = ROOT/'src/chat/utils/scene_context.py'
    source_bytes = source.read_bytes()
    tree = ast.parse(source_bytes.decode('utf-8-sig'))
    nodes: list[ast.stmt] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_parse_style_frontmatter']
    if len(nodes) != 1:
        raise RuntimeError('Parser extraction mismatch')
    namespace: dict[str, Any] = {'Dict': Dict}
    exec(compile(ast.Module(body=nodes, type_ignores=[]),str(source),'exec'), namespace)
    parse = namespace['_parse_style_frontmatter']
    paths = sorted((ROOT/'data/plugins').glob('*/chats/*/SKILL.md'))
    if not paths:
        raise RuntimeError('No profiles found')
    before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    rows = []
    for index, path in enumerate(paths):
        raw = path.read_bytes().decode('utf-8').replace('\r\n','\n').replace('\r','\n')
        old, new = legacy(raw), parse(raw)
        status = ('unchanged' if old == new else 'newly_rejected' if old and not new else 'changed')
        rows.append({'profile_index': index, 'status': status,
                     'previously_enabled': old.get('style_enabled') == 'true',
                     'currently_enabled': new.get('style_enabled') == 'true',
                     'manual_enabled': new.get('manual_style_enabled') == 'true',
                     'recognized_source': new.get('style_source') == 'owner_inbound_v1'})
    stable = set(paths) == set((ROOT/'data/plugins').glob('*/chats/*/SKILL.md')) and all(hashlib.sha256(p.read_bytes()).hexdigest() == sha for p, sha in before.items())
    source_stable = source.read_bytes() == source_bytes
    report = {'scope':'read-only actual parser function against all current profile files; not prompt assembly or migration',
              'source_sha256':hashlib.sha256(source_bytes).hexdigest(), 'profiles':rows,
              'profile_count':len(rows),'status_counts':dict(Counter(r['status'] for r in rows)),
              'enabled_before':sum(r['previously_enabled'] for r in rows),
              'enabled_after':sum(r['currently_enabled'] for r in rows),
              'manual_enabled':sum(r['manual_enabled'] for r in rows),
              'recognized_source':sum(r['recognized_source'] for r in rows),
              'profile_files_unchanged':stable,'parser_source_unchanged':source_stable}
    out = ROOT/'data/dialogue-evaluations'/('style-parser-audit-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    out.mkdir()
    (out/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != 'profiles'} | {'report':str(out/'report.json')}))
    return int(not stable or not source_stable or any(r['status'] != 'unchanged' for r in rows))

if __name__ == '__main__':
    raise SystemExit(main())
