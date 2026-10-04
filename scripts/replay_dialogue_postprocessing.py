"""离线回放清洗器差异；只输出聚合统计，不发送或导出聊天正文。"""
from collections import Counter
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugins'))
from telegram_user_adapter.humanize import humanize_chat_text


def replay(path: Path) -> dict:
    payload = path.read_bytes()
    counts = Counter()
    rules = Counter()
    seen = set()
    urls = re.compile(r'https?://[^\s<>]+')
    codes = re.compile(r'`[^`]+`')
    for line in payload.splitlines():
        try:
            row = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            counts['invalid_json'] += 1
            continue
        if not isinstance(row, dict) or row.get('direction') != 'out':
            continue
        mid = row.get('message_id')
        if mid is None:
            counts['missing_message_id'] += 1
            continue
        key = (str(row.get('chat_id')), str(mid))
        if key in seen:
            counts['duplicate'] += 1
            continue
        seen.add(key)
        original = row.get('original_text')
        if isinstance(original, str) and original:
            text = original
            counts['recorded_original'] += 1
        else:
            text = row.get('text')
            counts['sent_text_only'] += 1
        if not isinstance(text, str) or not text.strip():
            counts['empty'] += 1
            continue
        counts['samples'] += 1
        old = humanize_chat_text(text, preserve_semantics=False)
        new = humanize_chat_text(text, preserve_semantics=True)
        counts['legacy_changed'] += old.text != text
        counts['preserved_changed'] += new.text != text
        counts['legacy_emptied'] += bool(text.strip()) and not old.text.strip()
        counts['preserved_emptied'] += bool(text.strip()) and not new.text.strip()
        counts['legacy_url_changed'] += urls.findall(text) != urls.findall(old.text)
        counts['legacy_code_changed'] += codes.findall(text) != codes.findall(old.text)
        rules.update(old.applied_rules)
        assert new.text == text, '语义保留路径修改了文本'
    return {
        'schema': 1, 'input_sha256': hashlib.sha256(payload).hexdigest(),
        'counts': dict(counts), 'legacy_rules': dict(rules),
        'limitations': [
            '只有 recorded_original 是日志记录的改写前文本；sent_text_only 可能已被历史处理过。',
            '两路径使用相同函数的默认参数，不代表历史每次发送的真实群配置。',
            'URL/代码差异是结构变化计数，不自动等于语义错误。',
            '这是后处理离线对照，不是模型生成盲评，也不证明自然度提升。',
        ],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('transcript', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = replay(args.transcript)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
