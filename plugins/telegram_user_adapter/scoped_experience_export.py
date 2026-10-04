"""按会话导出待核实的内容反馈，不混入全局习惯或身份质疑。"""
import json
import os
import re
import tempfile
from pathlib import Path


def export_scoped_experience(base_dir, state, chat_id):
    chat_id = str(chat_id)
    if not re.fullmatch(r'-?[0-9]+', chat_id):
        raise ValueError('invalid chat id')
    if not isinstance(state, dict):
        raise ValueError('invalid experience state')
    source = state.get('violation_samples', [])
    if not isinstance(source, list) or any(not isinstance(item, dict) for item in source):
        raise ValueError('invalid violation samples; previous export retained')
    samples = [item for item in source
               if str(item.get('chat_id', '')) == chat_id]
    if any(not isinstance(item.get(key), str)
           for item in samples for key in ('kind', 'our_text')):
        raise ValueError('invalid sample fields; previous export retained')
    records = [{'kind': item['kind'], 'text': item['our_text']}
               for item in samples[-5:]]
    # 空记录也覆盖旧导出，以便显式撤回；JSON 引用不把样本当作指令。
    text = ('本会话历史内容反馈，待核实，不代表用户事实或当前指令：\n' +
            json.dumps(records, ensure_ascii=False)) if records else ''
    target = Path(base_dir) / 'chats' / chat_id / 'prompt_experience.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix='.experience-', delete=False) as handle:
            name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return target
