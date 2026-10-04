"""已实测选择结果到回复对照；只导入SDK，不启动生产运行时。"""
import ast
import json
import os
from pathlib import Path
import tomllib
from uuid import uuid4
from typing import Any, List
from openai import OpenAI


def main():
    os.umask(0o077)
    parent=Path('data/dialogue-evaluations/selector-shape-0be361d1/results.json')
    selection=json.loads(parent.read_text())
    chosen=[r for r in selection['results'] if r.get('finish_reason')=='stop']
    assert len(chosen)==2
    ids=json.loads(chosen[0]['output'])['selected_ids']
    assert ids==json.loads(chosen[1]['output'])['selected_ids']==[1]
    fixture=json.loads(Path(selection['source']).read_text())
    candidates=[c for c in fixture['candidates'] if c['id'] in ids]
    tree=ast.parse(Path('src/chat/replyer/maisaka_expression_selector.py').read_text(encoding='utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MaisakaExpressionSelector')
    fn=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_build_expression_habits_block')
    fn.decorator_list=[]
    ns={'List':List,'Any':Any}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<real-expression-formatter>','exec'),ns)
    block=ns[fn.name](candidates)
    source=Path('data/dialogue-evaluations/isolated-regression-20260920T205757Z-71ecca5c/assembled-style-json-off.json')
    system=[m for m in json.loads(source.read_text())['messages'] if m['role']=='system']
    out=Path('data/dialogue-evaluations')/('selected-expression-reply-'+uuid4().hex[:8]);out.mkdir()
    report={'scope':'recorded real selector outputs, actual AST expression formatter, exported core-persona system, synthetic target; direct SDK assembly, not full runtime chain','selection_source':str(parent),'system_source':str(source),'selected_ids':ids,'rubric':'acknowledge frustration; no advice, ridicule, invented personal experience or unsupported motive claims','results':[]}
    (out/'input.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    cfg=tomllib.loads(Path('config/model_config.toml').read_text());task=cfg['model_task_config']['replyer']
    model=next(m for m in cfg['models'] if m['name']==task['model_list'][0]);provider=next(p for p in cfg['api_providers'] if p['name']==model['api_provider'])
    with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=45,max_retries=0) as client:
        for variant in ('without_expression','selected_expression'):
            messages=system+([{'role':'user','content':block}] if variant=='selected_expression' else [])+[{'role':'user','content':fixture['target']}]
            row={'variant':variant,'messages':messages}
            (out/'pending.json').write_text(json.dumps(row,ensure_ascii=False))
            try:
                r=client.chat.completions.create(model=model['model_identifier'],messages=messages,temperature=task['temperature'],max_tokens=task['max_tokens'],stream=False,extra_body={k:v for k,v in model.get('extra_params',{}).items() if k not in ('stream_options','stream','messages','model','temperature','max_tokens')})
                c=next(c for c in r.choices if c.index==0)
                row.update(output=c.message.content,finish_reason=c.finish_reason)
            except Exception as exc:
                row['error_type']=type(exc).__name__
            report['results'].append(row)
            (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'directory':str(out),'results':[{k:v for k,v in r.items() if k!='messages'} for r in report['results']]},ensure_ascii=False))

if __name__=='__main__':
    main()
