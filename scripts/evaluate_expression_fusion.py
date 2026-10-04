"""对既有真实 embedding 结果做固定策略对照；不修改源证据或生产策略。"""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4


def evaluate(report):
    if report.get('status') != 'complete' or not report.get('rows'):
        raise ValueError('source incomplete')
    rows = []
    for source in report['rows']:
        target = source['target_only']
        context = source['target_plus_reason']
        a, b = target['scores'], context['scores']
        if len(a) != len(b) or not a:
            raise ValueError('score coverage mismatch')
        import math
        if not all(math.isfinite(x) for x in a + b):
            raise ValueError('nonfinite score')
        expected = source['expected_id']
        row = {'case': source['case'], 'expected_id': expected, 'strategies': {}}
        # 预先固定的对照权重；仅报告，不从这些样本中选最佳权重。
        for weight in (0.5, 0.75):
            scores = [weight*x + (1-weight)*y for x,y in zip(a,b)]
            ranking = sorted(range(len(scores)), key=lambda i: (-scores[i], i))
            row['strategies'][f'target_weight_{weight}'] = {
                'ranking': ranking, 'scores': scores, 'top1_correct': ranking[0] == expected}
        union = list(dict.fromkeys([target['ranking'][0], context['ranking'][0]]))
        row['dual_top1_union'] = {'ids': union, 'count': len(union), 'expected_present': expected in union}
        rows.append(row)
    return {'rows': rows, 'summary': {
        'case_count': len(rows),
        'fusion_top1_correct': {key: sum(r['strategies'][key]['top1_correct'] for r in rows)
                               for key in rows[0]['strategies']},
        'union_expected_present': sum(r['dual_top1_union']['expected_present'] for r in rows),
        'union_total_candidates': sum(r['dual_top1_union']['count'] for r in rows)},
        'decision': 'not_deployed',
        'limitations': 'Same five development cases and three obvious candidates; union coverage is not final selection accuracy. Scores are reused, no production clustering/MMR or reranker execution.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    report = evaluate(json.loads(args.source.read_text()))
    report['source'] = str(args.source.resolve())
    out = args.source.parent.parent / ('fusion-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    out.mkdir()
    path = out / 'result.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(path)
    print(json.dumps(report['summary'], ensure_ascii=False))

if __name__ == '__main__':
    main()
