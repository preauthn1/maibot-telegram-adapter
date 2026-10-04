"""AST加载纯清单函数，合成目录验证输入变更可检测。"""
import ast
import hashlib
from pathlib import Path


def test_fixture_manifest_tracks_add_edit_delete(tmp_path):
    source=Path('scripts/run_isolated_dialogue_tests.py').read_text()
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='fixture_hashes')
    ns={'ROOT':tmp_path,'hashlib':hashlib}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'fixture-function','exec'),ns)
    scan=ns['fixture_hashes']
    p=tmp_path/'tests/fixtures/synthetic.json'
    p.parent.mkdir(parents=True)
    p.write_text('{}')
    first=scan()
    assert set(first)=={'tests/fixtures/synthetic.json'}
    p.write_text('{"changed":true}')
    assert scan()!=first
    q=tmp_path/'plugins/telegram_user_adapter/tests/synthetic.json'
    q.parent.mkdir(parents=True)
    q.write_text('[]')
    assert len(scan())==2
    p.unlink()
    assert set(scan())=={'plugins/telegram_user_adapter/tests/synthetic.json'}
