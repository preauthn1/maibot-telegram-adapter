"""候选预算覆盖审计；余弦排名回放，不冒充生产 MMR。"""
import json
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import argparse


def audit(source):
    if source.get('status') != 'complete':
        raise ValueError('incomplete source')
    n = len(source['candidates'])
    rows = source['rows']
    if not rows or n < 1:
        raise ValueError('empty source')
    result = {}
    for variant in ('target_plus_reason', 'target_only'):
        ranks = []
        for row in rows:
            ranking = row[variant]['ranking']
            if sorted(ranking) != list(range(n)):
                raise ValueError('invalid ranking coverage')
            ranks.append(dict(case=row['case'], rank=ranking.index(row['expected_id']) + 1))
        result[variant] = dict(ranks=ranks, coverage={str(k):sum(r['rank'] <= k for r in ranks)
                              for k in (1,3,5,10,n) if k <= n})
    return dict(case_count=len(rows), candidate_count=n, variants=result,
                scope='Saved real embedding cosine ranking only; not production MMR, legacy sampling, or final selection', deployment='not_applied')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    args = p.parse_args()
    report = audit(json.loads(args.source.read_text()))
    report['source'] = str(args.source.resolve())
    out = args.source.parent.parent / ('recall-coverage-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    out.mkdir()
    (out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(out/'result.json')
    print(json.dumps(report,ensure_ascii=False))

if __name__ == '__main__':
    main()
