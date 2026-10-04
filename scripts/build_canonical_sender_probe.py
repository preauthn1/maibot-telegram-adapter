"""仅转换已知合成fixture的源码生成前缀，不处理真实聊天正文。"""
import json
import re
from pathlib import Path
from html import escape, unescape

ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'tests/fixtures/dialogue_sender_transfer_v1.json'
original=json.loads(source.read_text())
selected=[c for c in original if c['id'].endswith('_with_sender')]
output=[]
for case in selected:
    output.append(case)
    mapping={}
    def convert(text):
        prefix,sep,body=text.partition('\n')
        if not sep or not prefix.startswith('<message '): raise ValueError('Invalid fixture prefix')
        attrs=dict(re.findall(r'(\w+)="([^"]*)"',prefix))
        key=(unescape(attrs['sender_platform']),unescape(attrs['sender_id']))
        if key not in mapping: mapping[key]='账号'+chr(ord('A')+len(mapping))
        display=attrs['user']
        result=re.sub(r'(?<= )user="[^"]*"', 'user="'+mapping[key]+'" display_name="'+display+'"',prefix,count=1)+'\n'+body
        if result.partition('\n')[2]!=body: raise RuntimeError('Body changed')
        return result
    candidate={**case,'id':case['id']+'_canonical',
        'history':[{'role':m['role'],'content':convert(m['content'])} for m in case['history']],
        'question':convert(case['question'])}
    output.append(candidate)
path=ROOT/'tests/fixtures/dialogue_canonical_sender_probe_v1.json'
path.write_text(json.dumps(output,ensure_ascii=False,indent=2))
print(json.dumps({'cases':len(output),'fixture':str(path),'scope':'synthetic prefix representation only; no production deployment'}))
