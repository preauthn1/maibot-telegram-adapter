"""纯数据预检：先验证成对请求，之后才允许联网。"""
from copy import deepcopy
import re

TARGET = re.compile(r'<sender sender_id="[^"]*" sender_platform="[^"]*" />\n')


def build_pair(record):
    messages = record.get('messages')
    if not isinstance(messages, list) or not messages:
        raise ValueError('Expected nonempty message list')
    if any(not isinstance(m, dict) or m.get('role') not in ('system', 'user', 'assistant', 'tool') for m in messages):
        raise ValueError('Invalid message structure')
    final = messages[-1]
    if final['role'] != 'user' or not isinstance(final.get('content'), str):
        raise ValueError('Expected final user text')
    if len(TARGET.findall(final['content'])) != 1:
        raise ValueError('Expected exactly one target identity')
    assembled = deepcopy(messages)
    control = deepcopy(messages)
    control[-1]['content'] = TARGET.sub('', final['content'])
    return {'assembled': assembled, 'without_target_identity': control}
