"""原始选择提示与解析器实呼；AST提取避免生产运行时导入。"""
import ast
import hashlib
import json
import os
from pathlib import Path
import tomllib
from uuid import uuid4
from json_repair import repair_json
from openai import OpenAI


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-task', choices=('planner', 'replyer'), default='planner')
    parser.add_argument('--user-trigger', action='store_true', help='诊断用显式用户触发，不代表真实父历史')
    parser.add_argument('--no-suitable-candidates', action='store_true', help='移除适合倾诉的候选，预期拒选')
    parser.add_argument('--synthetic-parent', action='store_true', help='合成父对话，不经过运行时筛选')
    args = parser.parse_args()
    if args.synthetic_parent and args.user_trigger:
        parser.error('Choose either parent context or diagnostic trigger')
    os.umask(0o077)
    source=Path('src/chat/replyer/maisaka_expression_selector.py').read_bytes()
    tree=ast.parse(source.decode('utf-8-sig'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='MaisakaExpressionSelector')
    names={'_build_selector_prompt','_parse_selected_ids'}
    methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names]
    assert len(methods)==2
    from typing import Any,List
    import logging
    namespace=dict(Any=Any,List=List,MAX_SELECTED_EXPRESSIONS=5,json=json,repair_json=repair_json,logger=logging.getLogger('probe'))
    exec(compile(ast.Module(body=methods,type_ignores=[]),'<extracted-selector>','exec'),namespace)
    candidates=[{'id':i,'situation':s,'style':t} for i,(s,t) in enumerate([
        ('倾诉且不想要建议','回应对方被含糊评价后的憋屈，不提供解决步骤'),
        ('请求排障','分步骤列出原因和解决方案'),
        ('轻松互损','用哈哈开场并调侃对方太敏感'),
        ('庆祝成果','兴奋地祝贺对方'),
        ('核对事实','只陈述有依据的事实，不补造细节'),
        ('求安慰','声称自己昨天也亲历了同样事件'),
        ('用户要结束','简短告别'),
        ('请求代码','提供可执行代码'),
        ('用户询问天气','报告天气'),
        ('请求翻译','忠实翻译原文')],1)]
    target='方案改了三次，领导每次只说感觉不对。我现在只想吐槽，别给建议。'
    if args.no_suitable_candidates:
        candidates = [c for c in candidates if c['id'] not in (1, 5)]
    prompt=namespace['_build_selector_prompt'](None,candidates=candidates,target_message=target,reply_reason='回应倾诉')
    out=Path('data/dialogue-evaluations')/('expression-selector-live-'+uuid4().hex[:8]);out.mkdir()
    report={'scope':'original AST-extracted selector prompt/parser; synthetic candidates; explicit model task, not production subagent runner or retrieval', 'model_task':args.model_task,'source_sha256':hashlib.sha256(source).hexdigest(),'candidates':candidates,'target':target,'prompt':prompt,'rubric':{'preferred':[1],'disallowed':[2,3,4,6,7,8,9,10],'empty_allowed':True}}
    messages = [{'role':'system','content':prompt}]
    if args.user_trigger:
        messages.append({'role':'user','content':'请根据当前目标消息选择表达方式，仅返回所要求的 JSON。'})
    if args.synthetic_parent:
        messages.extend([
            {'role':'user','content':'方案一直改不好，你能给我点建议吗？'},
            {'role':'assistant','content':'可以先确认具体哪些地方需要调整。'},
            {'role':'user','content':target},
        ])
    report.update(user_trigger=args.user_trigger, synthetic_parent=args.synthetic_parent, no_suitable_candidates=args.no_suitable_candidates, messages=messages)
    if args.no_suitable_candidates:
        report['rubric'] = {'preferred':[], 'disallowed':[c['id'] for c in candidates], 'empty_required':True}
    (out/'input.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    cfg=tomllib.loads(Path('config/model_config.toml').read_text());task=cfg['model_task_config'][args.model_task]
    model=next(m for m in cfg['models'] if m['name']==task['model_list'][0]);provider=next(p for p in cfg['api_providers'] if p['name']==model['api_provider'])
    try:
        with OpenAI(api_key=provider['api_key'],base_url=provider['base_url'],timeout=90,max_retries=0) as client:
            response=client.chat.completions.create(model=model['model_identifier'],messages=messages,temperature=task['temperature'],max_tokens=task['max_tokens'],stream=False,extra_body={k:v for k,v in model.get('extra_params',{}).items() if k not in ('stream_options','stream','messages','model','temperature','max_tokens')})
        c=next(c for c in response.choices if c.index==0)
        if c.finish_reason!='stop' or not isinstance(c.message.content,str) or not c.message.content.strip():
            raise ValueError('Incomplete response')
        ids=namespace['_parse_selected_ids'](None,c.message.content,candidates)
        report.update(output=c.message.content,selected_ids=ids,disallowed_selected=sorted(set(ids)&set(report['rubric']['disallowed'])))
    except Exception as exc:
        report['error_type']=type(exc).__name__
    (out/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'directory':str(out),**{k:report[k] for k in ('output','selected_ids','disallowed_selected','error_type') if k in report}},ensure_ascii=False))
    return int('error_type' in report)

if __name__=='__main__':
    raise SystemExit(main())
