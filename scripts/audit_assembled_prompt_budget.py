"""只读统计导出提示的组成及真实上游用量；字符数不冒充 token。"""
import argparse
import hashlib
import json
from pathlib import Path


def audit(source, results):
    exports = {}
    for path in source.glob('assembled-*.json'):
        record = json.loads(path.read_text())
        key = record['sample_id']
        if key in exports:
            raise ValueError('Duplicate sample')
        exports[key] = (path, record)
    rows = []
    seen = set()
    for result in json.loads(results.read_text())['results']:
        key = result['sample_id']
        if key in seen:
            raise ValueError('Duplicate result')
        seen.add(key)
        path, record = exports[key]
        if hashlib.sha256(path.read_bytes()).hexdigest() != result['source_sha256']:
            raise ValueError('Source fingerprint mismatch')
        parts = []
        for index, message in enumerate(record['messages']):
            content = message['content']
            if isinstance(content, list):
                if any(p['type'] != 'text' for p in content):
                    raise ValueError('Non-text content requires separate accounting')
                content = ''.join(p['text'] for p in content)
            parts.append({'index':index,'role':message['role'],'characters':len(content)})
        usages = [result.get('usage') or {}]
        if result.get('fallback_attempted'):
            usages.insert(0, (result.get('stream_attempt') or {}).get('usage') or {})
        tokens = dict.fromkeys(('prompt_tokens','completion_tokens','total_tokens'), 0)
        for usage in usages:
            if any(type(usage.get(k)) is not int or usage[k] < 0 for k in tokens):
                raise ValueError('Missing valid reported token usage')
            for key_name in tokens:
                tokens[key_name] += usage[key_name]
        rows.append({'sample_id':key,'messages':parts,'characters':sum(p['characters'] for p in parts),
                     'reported_usage':tokens,'attempt_count':len(usages),'exact_match':result['passed'],'elapsed_seconds':result['elapsed_seconds']})
    if not rows or seen != set(exports):
        raise ValueError('Incomplete export/result coverage')
    return {'scope':'synthetic assembled prompt accounting; no per-message tokenizer attribution',
            'samples':rows,'reported_token_totals':{k:sum(r['reported_usage'][k] for r in rows) for k in tokens},
            'warning':'Output token count may include reasoning; no truncation or production tuning applied.'}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source',type=Path)
    parser.add_argument('results',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    report = audit(args.source,args.results)
    with args.output.open('x') as handle:
        json.dump(report,handle,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False))
