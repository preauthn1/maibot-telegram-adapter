"""从真实前缀函数构造合成账号消融；不导入有数据库副作用的运行时。"""
import ast
from datetime import datetime
from html import escape
import json
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
source = ROOT/'src/maisaka/context/planner_messages.py'
tree = ast.parse(source.read_text(encoding='utf-8-sig'))
names = {'build_planner_prefix', '_format_quote_ids'}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
if len(nodes) != 2:
    raise RuntimeError('Missing prefix functions')
namespace = dict(datetime=datetime, escape=escape, Optional=Optional, Sequence=Sequence)
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),namespace)
build = namespace['build_planner_prefix']
cases = []
for enabled in (False,True):
    history = []
    for i,(uid,body) in enumerate([('17','我养的猫叫栗子。'),('29','我养的兔子叫豆包。'),('17','更正，我的猫叫松子。')]):
        prefix = build(timestamp=datetime(2026,1,1,12,0,i),user_name='小陈',group_card='小陈',message_id=f'm{i}',
                       **({'sender_id':uid,'sender_platform':'telegram'} if enabled else {}))
        history.append({'role':'user','content':prefix+body})
    prefix = build(timestamp=datetime(2026,1,1,12,0,4),user_name='小陈',group_card='小陈',message_id='m4',
                   **({'sender_id':'29','sender_platform':'telegram'} if enabled else {}))
    cases.append({'id':'with_sender' if enabled else 'without_sender','history':history,
                  'question':prefix+'我养的是什么、叫什么？不确定就说明不确定。',
                  'rubric':'With sender: account29 rabbit 豆包. Without sender: insufficient account attribution, must not confidently choose. No inference about real-world identity.'})
# 唯一消融变量为两个新增属性；所有时间、消息ID、正文保持一致。
import re
strip=lambda s: re.sub(r' sender_(?:id|platform)="[^"]*"','',s)
for a,b in zip(cases[0]['history'],cases[1]['history']):
    if a['content'] != strip(b['content']): raise RuntimeError('Ablation mismatch')
if cases[0]['question'] != strip(cases[1]['question']): raise RuntimeError('Question mismatch')
out=ROOT/'tests/fixtures/dialogue_sender_identity_ablation_v1.json'
out.write_text(json.dumps(cases,ensure_ascii=False,indent=2))
print(json.dumps({'fixture':str(out),'cases':len(cases),'only_sender_attributes_differ':True}))
