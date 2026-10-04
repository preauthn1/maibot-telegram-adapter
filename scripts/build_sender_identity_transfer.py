"""预先固定身份迁移消融；使用真实前缀函数，不导入应用运行时。"""
import ast
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
from typing import Any, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
source = ROOT/'src/maisaka/context/planner_messages.py'
tree = ast.parse(source.read_text(encoding='utf-8-sig'))
nodes: list[ast.stmt] = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'build_planner_prefix','_format_quote_ids'}]
if len(nodes) != 2: raise RuntimeError('Missing functions')
ns: dict[str, Any] = dict(datetime=datetime,escape=escape,Optional=Optional,Sequence=Sequence)
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),ns)
build = ns['build_planner_prefix']
scenarios = [
 ('renamed_account', [('telegram','51','秋叶','我报名的是陶艺课。'),('telegram','62','冬青','我报名的是摄影课。')],
  ('telegram','51','新芽','我报名的是什么课？没法确定就说不确定。'),
  '带标识：当前51账号是陶艺课；无标识：新昵称无法可靠关联，应该说明不确定。'),
 ('cross_platform_same_id', [('telegram','77','小雨','我的预约是周二。'),('qq','77','小雨','我的预约是周四。')],
  ('telegram','77','小雨','我的预约是哪天？没法确定就说不确定。'),
  '带标识：telegram账号77预约周二，不是qq账号77的周四；无标识：同名且无平台，不能确定当前提问者预约。')
]
cases=[]
for sid,turns,question,rubric in scenarios:
    pair=[]
    for enabled in (True,False):
        def render(record,index):
            platform,uid,name,body=record
            return build(timestamp=datetime(2026,1,1,12,0,index),user_name=name,message_id=f'm{index}',
                **({'sender_id':uid,'sender_platform':platform} if enabled else {}))+body
        pair.append({'id':sid+('_with_sender' if enabled else '_without_sender'),
            'history':[{'role':'user','content':render(row,i)} for i,row in enumerate(turns)],
            'question':render(question,4),'rubric':rubric})
    strip=lambda text: re.sub(r' sender_(?:id|platform)="[^"]*"','',text)
    if any(strip(a['content']) != b['content'] for a,b in zip(pair[0]['history'],pair[1]['history'])) or strip(pair[0]['question'])!=pair[1]['question']:
        raise RuntimeError('Uncontrolled difference')
    cases.extend(pair)
out=ROOT/'tests/fixtures/dialogue_sender_transfer_v1.json'
out.write_text(json.dumps(cases,ensure_ascii=False,indent=2))
print(json.dumps({'fixture':str(out),'cases':len(cases),'only_sender_attributes_differ':True,'order':'with then without'}))
