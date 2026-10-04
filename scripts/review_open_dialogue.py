"""将本次人工语义判断绑定到真实响应；不是自动语义评分器。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'baseline': '20260919T190634Z-fc527779',
    'intent_fit': '20260919T190826Z-cfa9a815',
}


def review_row(variant, scenario, index, row):
    findings = []
    if scenario == 'casual' and index == 0 and variant == 'baseline':
        quote = '尤其卫星轴、定位板这些地方会放大共振'
        assert quote in row['output']
        findings.append({'dimension': 'intent_fit', 'verdict': 'concern', 'quote': quote,
                         'reason': '用户分享声音趣事，并未询问原理；额外解释偏离主要交流意图。'})
    if scenario == 'emotion' and index == 0 and variant == 'intent_fit':
        for dimension, quote, reason in [
            ('grounding', '尤其你已经认真准备了', '当前输入未说明准备程度，把推测写成事实。'),
            ('instruction_following', '先让它待一会儿吧', '用户明确不要建议，这仍是行动导向的建议。'),
        ]:
            assert quote in row['output']
            findings.append({'dimension': dimension, 'verdict': 'fail', 'quote': quote, 'reason': reason})
    return {'scenario': scenario, 'turn': index + 1,
            'request_sha256': row['request']['request_sha256'],
            'input_messages': row['request']['messages'][1:], 'output': row['output'],
            'completion_status': row['completion_status'], 'findings': findings,
            'review_status': 'finding_recorded' if findings else 'not_scored',
            'naturalness': 'not_scored'}


def main():
    reports = []
    for variant, run in SOURCES.items():
        source = ROOT / 'data/dialogue-evaluations' / run / 'rollout.json'
        report = json.loads(source.read_text())
        assert report['suite'] == 'open_dialogue_v1'
        assert report['variant'] == ('current' if variant == 'baseline' else variant)
        checks = [review_row(variant, name, i, row)
                  for name, rows in report['scenarios'].items() for i, row in enumerate(rows)]
        assert len(checks) == report['expected_turns'] == 7
        reports.append({'variant': variant, 'source': str(source.relative_to(ROOT)), 'checks': checks})
    output = ROOT / 'data/dialogue-evaluations/open-dialogue-semantic-review-v1.json'
    result = {'reviewer': 'assistant qualitative review, not independent blind review',
              'scope': 'selected failure annotations; unannotated rows are not passes', 'reports': reports}
    with output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(output)
    print(json.dumps({'rows': sum(len(r['checks']) for r in reports),
                      'findings': sum(len(c['findings']) for r in reports for c in r['checks'])}))


if __name__ == '__main__':
    main()
