"""只读语料审计：固定输入摘要，输出聚合数据，不导出聊天正文。"""
from collections import Counter
from pathlib import Path
from statistics import median
import argparse
import hashlib
import json


def audit(path: Path, owner_id: str) -> dict:
    # 一次读取固定快照，避免日志追加造成摘要和统计对应不同输入。
    payload = path.read_bytes()
    counts = Counter()
    seen = set()
    texts = {'account_output': [], 'other_members_unknown': []}
    for line in payload.splitlines():
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            counts['invalid_json'] += 1
            continue
        if not isinstance(row, dict):
            counts['invalid_record'] += 1
            continue
        direction = row.get('direction')
        if direction not in ('in', 'out'):
            counts['non_message'] += 1
            continue
        if direction == 'in' and row.get('is_private') is not False:
            counts['private_or_unspecified'] += 1
            continue
        if direction == 'in' and not str(row.get('sender_id') or '').strip():
            counts['missing_sender'] += 1
            continue
        if direction == 'in' and str(row.get('sender_id')) == owner_id:
            counts['owner_inbound_excluded'] += 1
            continue
        mid = row.get('message_id')
        if mid is None:
            counts['missing_message_id'] += 1
            continue
        key = (str(row.get('chat_id')), direction, str(mid))
        if key in seen:
            counts['duplicate'] += 1
            continue
        seen.add(key)
        text = str(row.get('text') or '').strip()
        if text.startswith('[回复<'):
            _, separator, text = text.partition(']，说：')
            if not separator:
                counts['malformed_reply'] += 1
                continue
            counts['reply_body_extracted'] += 1
            text = text.strip()
        if not text or text.startswith(('[文件:', '[图片:', '[视频:', '[语音:')):
            counts['empty_or_attachment'] += 1
            continue
        bucket = 'account_output' if direction == 'out' else 'other_members_unknown'
        texts[bucket].append(text)
        counts['accepted'] += 1
    metrics = {}
    for label, values in texts.items():
        lengths = sorted(map(len, values))
        n = len(values)
        metrics[label] = {
            'samples': n,
            'median_chars': median(lengths) if n else None,
            'p90_chars_nearest_rank': lengths[max(0, (9*n+9)//10-1)] if n else None,
            'question_mark_rate': sum('?' in x or '？' in x for x in values)/n if n else None,
            'unique_text_ratio': len(set(values))/n if n else None,
        }
    return {'schema': 1, 'sha256': hashlib.sha256(payload).hexdigest(),
            'bytes': len(payload), 'lines': len(payload.splitlines()),
            'counts': dict(counts), 'metrics': metrics,
            'limitations': ['入站身份未验证，不能称为真人金标准。',
                            '引用头按旧协议首个分隔符解析，文本内嵌同名分隔符存在歧义。',
                            '本报告不是模型对照评测，不能证明自然度提升。']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('transcript', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    account_path = args.transcript.parent.parent / 'account_profile.json'
    owner_id = str(json.loads(account_path.read_text(encoding='utf-8'))['user_id'])
    if not owner_id:
        raise ValueError('缺少账号 ID，拒绝混合来源')
    report = audit(args.transcript, owner_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
