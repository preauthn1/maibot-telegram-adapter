"""对既有合成装配导出做平台边界压力测试；不导入运行时。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4


def main():
    p=argparse.ArgumentParser(); p.add_argument('source',type=Path); a=p.parse_args()
    os.umask(0o077)
    raw=a.source.read_bytes(); record=json.loads(raw)
    messages=record['messages']
    def replace(entry, old, new):
        content=entry['content']
        if isinstance(content,str):
            if content.count(old)!=1: raise ValueError('Expected unique metadata')
            entry['content']=content.replace(old,new,1)
        elif isinstance(content,list):
            parts=[x for x in content if x.get('type')=='text' and old in x.get('text','')]
            if len(parts)!=1 or parts[0]['text'].count(old)!=1: raise ValueError('Expected unique text metadata')
            parts[0]['text']=parts[0]['text'].replace(old,new,1)
        else: raise ValueError('Unsupported content')
    # 猫：telegram/77；兔：qq/77；目标telegram/77。
    replace(messages[1],'sender_id="17"','sender_id="77"')
    replace(messages[2],'sender_id="29"','sender_id="77"')
    replace(messages[2],'sender_platform="telegram"','sender_platform="qq"')
    replace(messages[-1],'sender_id="17"','sender_id="77"')
    original=json.loads(raw)['messages']
    restored=json.loads(json.dumps(messages))
    replace(restored[1],'sender_id="77"','sender_id="17"')
    replace(restored[2],'sender_id="77"','sender_id="29"')
    replace(restored[2],'sender_platform="qq"','sender_platform="telegram"')
    replace(restored[-1],'sender_id="77"','sender_id="17"')
    if restored!=original: raise RuntimeError('Uncontrolled difference')
    record.update(scope='metadata-transformed real assembly export; synthetic cross-platform stress test, not production cross-platform routing',
                  parent_sha256=hashlib.sha256(raw).hexdigest(),expected='猫，松子',only_identity_metadata_changed=True)
    out=a.source.parent/('platform-probe-'+uuid4().hex[:8]);out.mkdir()
    path=out/'request.json';path.write_text(json.dumps(record,ensure_ascii=False,indent=2))
    print(path)

if __name__=='__main__':main()
