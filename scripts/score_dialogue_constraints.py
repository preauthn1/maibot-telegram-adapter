"""合成评测的窄范围约束审计，不作为自然度或技术正确性评分。"""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json
import re


def assess(row: dict) -> dict:
    case = row['case'].split('__r')[0]
    text = row.get('output')
    result = {'case': row['case'], 'variant': row['variant'], 'status': 'review', 'signals': []}
    if row.get('finish_reason') == 'length' or row.get('completion_status') in ('truncated', 'empty', 'unverified_finish'):
        return dict(result, status='invalid', signals=['incomplete_or_unverified_generation'])
    if not row.get('ok') or not isinstance(text, str) or not text.strip():
        return dict(result, status='invalid', signals=['missing_output'])
    if case == 'memory_provided':
        correct = text.strip().rstrip('。.!！') == '豆豆'
        return dict(result, status='pass' if correct else 'flag', signals=[] if correct else ['not_requested_name_only'])
    if case == 'no_advice':
        # 这些是候选违规信号，不是通用的语言语义判定器。
        signals = []
        if re.search(r'歇|休息|试试|建议|不妨|你可以|不用管|什么都不用管', text):
            signals.append('possible_unsolicited_advice')
        if re.search(r'[？?]', text):
            signals.append('question_despite_no_questions')
        return dict(result, status='flag' if signals else 'review', signals=signals)
    if case == 'log_present':
        signals = []
        if re.search(r'没(?:有)?(?:看|收)到|重新发|再发一次|发送失败', text):
            signals.append('denies_available_text')
        if re.search(r'建议|执行|运行|检查|续期', text):
            signals.append('possible_unrequested_diagnosis')
        return dict(result, status='flag' if signals else 'review', signals=signals)
    if case == 'detail_requested':
        missing = [x for x in ('备份', '验证', '回滚') if x not in text]
        return dict(result, status='flag' if missing else 'review',
                    signals=['missing_section:'+x for x in missing] + ['technical_correctness_not_checked'])
    return dict(result, signals=['no_automatic_rubric'])


def score(path: Path) -> dict:
    payload = path.read_bytes()
    source = json.loads(payload)
    rows = source['cases']
    keys = [(r['case'], r['variant']) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('重复样本标识，拒绝计算汇总')
    results = [assess(r) for r in rows]
    totals = Counter(r['status'] for r in results)
    return {'source_sha256': hashlib.sha256(payload).hexdigest(), 'samples': len(results),
            'counts': dict(totals), 'results': results,
            'scope': '约束筛查；flag 是待复核信号，review 不是通过；不衡量自然度或技术正确性。'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = score(args.input)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
