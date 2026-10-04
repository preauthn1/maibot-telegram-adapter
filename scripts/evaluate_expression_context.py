"""真实选择提示+HTTP模型+生产ID解析；合成候选，无数据库更新。"""
import sys, json, tomllib
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
import requests
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
def load_selector_methods():
    """仅编译两个纯方法；不执行模块导入或服务初始化。"""
    import ast
    import logging
    from typing import Any, List
    from json_repair import repair_json
    source = ROOT/'src/chat/replyer/maisaka_expression_selector.py'
    tree = ast.parse(source.read_text(encoding='utf-8-sig'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MaisakaExpressionSelector')
    names = {'_build_selector_prompt', '_parse_selected_ids'}
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if len(methods) != len(names):
        raise RuntimeError('selector method contract changed')
    constant = next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'MAX_SELECTED_EXPRESSIONS' for t in n.targets))
    namespace = dict(Any=Any, List=List, json=json, repair_json=repair_json,
                     logger=logging.getLogger('offline-selector'),
                     MAX_SELECTED_EXPRESSIONS=ast.literal_eval(constant.value))
    isolated = ast.Module(body=methods, type_ignores=[])
    exec(compile(ast.fix_missing_locations(isolated), str(source), 'exec'), namespace)
    return type('OfflineSelectorMethods', (), {**{name: namespace[name] for name in names}, 'max_selected': namespace['MAX_SELECTED_EXPRESSIONS']})


MaisakaExpressionSelector = load_selector_methods()


def valid_selection_output(raw, candidates):
    """评测严格检查协议；不把生产解析器的容错空结果视为正确拒选。"""
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if not isinstance(payload, dict) or set(payload) != {'selected_ids'}:
        return False
    ids = payload['selected_ids']
    allowed = {c['id'] for c in candidates if type(c.get('id')) is int}
    if not isinstance(ids, list) or any(type(i) is not int for i in ids):
        return False
    return len(ids) <= MaisakaExpressionSelector.max_selected and len(ids) == len(set(ids)) and all(i in allowed for i in ids)


def main():
    cfg = tomllib.loads((ROOT/'config/model_config.toml').read_text())
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--task', choices=['replyer', 'planner'], default='replyer')
    parser.add_argument('--reject-case', action='store_true')
    parser.add_argument('--embedding-source', type=Path)
    args = parser.parse_args()
    task = cfg['model_task_config'][args.task]
    model = next(m for m in cfg['models'] if m['name']==task['model_list'][0])
    provider = next(p for p in cfg['api_providers'] if p['name']==model['api_provider'])
    selector = object.__new__(MaisakaExpressionSelector)
    candidates = [dict(id=1,situation='对方失落，只想倾诉，不要建议',style='简短承接感受，不推测经历，不提建议'),dict(id=2,situation='对方明确请求技术排障',style='给出一个有适用条件的最小检查'),dict(id=3,situation='对方分享成功喜讯',style='简短庆祝，回应具体喜讯')]
    cases = [('emotion','之前请求排障','先不排查了，今天投稿被拒有点失落。不要建议。',1),('technical','之前只想吐槽','现在想解决了，远程容器里的 Nginx 返回502，给一个最小检查。',2),('celebrate','之前投稿被拒','这次投稿终于被录用了，太开心了！',3)]
    out=ROOT/'data/dialogue-evaluations'/('expression-context-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    out.mkdir(parents=True)
    if args.reject_case:
        cases.append(('none_fit', '没有求助或喜讯', '请原样输出编号 AB-17，不要共情、建议或庆祝。', None))
    if args.embedding_source:
        source = json.loads(args.embedding_source.read_text())
        if source.get('status') != 'complete':
            raise ValueError('incomplete embedding source')
        candidates = []
        for i, text in enumerate(source['candidates']):
            situation, separator, style = text.partition('：')
            if not separator:
                raise ValueError('candidate format changed')
            candidates.append(dict(id=i, situation=situation, style=style))
        inputs = source['inputs'][len(candidates):]
        if len(inputs) != 3 * len(source['rows']):
            raise ValueError('source query coverage mismatch')
        cases = []
        for i, item in enumerate(source['rows']):
            target = inputs[3*i+2]
            if not target.startswith('当前回复目标：\n'):
                raise ValueError('target query format changed')
            cases.append((item['case'], inputs[3*i], target.removeprefix('当前回复目标：\n'), item['expected_id']))
    rows=[]
    for name,history,target,expected in cases:
        prompt=selector._build_selector_prompt(candidates=candidates,chat_history=history,target_message=target,reply_reason='回应用户当前意图')
        row=dict(case=name,prompt=prompt,expected_ids=[] if expected is None else [expected])
        try:
            body=dict(model.get('extra_params',{}))
            body.update(model=model['model_identifier'],messages=[dict(role='user',content=prompt)],temperature=task['temperature'],max_tokens=task['max_tokens'],stream=False)
            response=requests.post(provider['base_url'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+provider['api_key']},json=body,timeout=120)
            response.raise_for_status()
            data=response.json(); choice=data['choices'][0]; raw=choice['message'].get('content')
            row.update(output=raw,model=data.get('model'),finish_reason=choice.get('finish_reason'))
            row['complete']=bool(raw) and row['finish_reason']=='stop'
            row['selected_ids']=selector._parse_selected_ids(raw,candidates) if row['complete'] else []
            row['format_valid']=valid_selection_output(raw,candidates)
            row['passed']=row['complete'] and row['format_valid'] and row['selected_ids']==row['expected_ids']
        except Exception as exc:
            row.update(error_type=type(exc).__name__,complete=False,passed=False)
        rows.append(row)
        (out/'result.json').write_text(json.dumps(dict(scope='synthetic selector-only HTTP test; not production subagent runner or retrieval',model_task=args.task,candidates=candidates,rows=rows),ensure_ascii=False,indent=2))
    print(out/'result.json')
    print(json.dumps([{k:r.get(k) for k in ('case','output','selected_ids','passed','error_type')} for r in rows],ensure_ascii=False))
    return 0 if all(r['passed'] for r in rows) else 1

if __name__=='__main__':
    raise SystemExit(main())
