"""真实模型产物经 codec 离线回放；本地假发送器，不连接平台。"""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugins/telegram_user_adapter/tests'))
from test_low_information_outbound import make_codec, send
from telegram_user_adapter.codecs import outbound


def deny_dns(*args, **kwargs):
    raise RuntimeError('network disabled in offline replay')


async def replay(paths):
    rows = []
    original_dns = outbound.verify_urls_resolvable
    outbound.verify_urls_resolvable = deny_dns
    try:
        for path in paths:
            document = json.loads(path.read_text())
            for index, record in enumerate(document['records']):
                row = dict(source=str(path.relative_to(ROOT)), index=index,
                           variant=record['variant'], case=record['case'])
                if record['completion_status'] != 'complete':
                    row['status'] = 'generation_incomplete'
                else:
                    text = record['output']
                    codec, sender = make_codec()
                    codec._enable_humanize = True
                    try:
                        result = await send(codec, text)
                        row.update(original=text, sent=sender.sent,
                                   status=('preserved' if sender.sent == [text] else 'modified')
                                   if result is not None else 'blocked')
                    except Exception as exc:
                        row.update(status='replay_error', error_type=type(exc).__name__)
                rows.append(row)
    finally:
        outbound.verify_urls_resolvable = original_dns
    from collections import Counter
    return {'scope': 'saved synthetic model outputs; real single-segment codec; independent fresh guards; no queue, actual platform, or conversational rate simulation',
            'rows': rows, 'counts': dict(Counter(row['status'] for row in rows)),
            'total': len(rows)}


if __name__ == '__main__':
    paths = [ROOT / 'data/dialogue-evaluations' / name / 'result.json' for name in (
        'short-style-20260919T202909Z-6e27fb44',
        'short-style-20260919T203024Z-581c359a',
        'short-style-20260919T203341Z-672c5d34',
        'short-style-20260919T203615Z-376e860e',
        'short-style-20260919T203918Z-410856b1')]
    report = asyncio.run(replay(paths))
    output = ROOT / 'data/dialogue-evaluations' / ('short-outbound-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8] + '.json')
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(output)
    print(json.dumps({'counts': report['counts'], 'total': report['total']}))
