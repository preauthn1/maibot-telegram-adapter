"""拒选必须是有效协议，不是解析失败产生的空列表。"""
import runpy
from pathlib import Path
import pytest

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[3] / 'scripts/evaluate_expression_context.py'))

@pytest.mark.parametrize('raw,valid', [
    ('{"selected_ids":[]}', True), ('{"selected_ids":[1]}', True),
    ('garbage', False), ('{}', False), ('[]', False),
    ('{"selected_ids":[true]}', False), ('{"selected_ids":[999]}', False),
    ('{"selected_ids":[1,1]}', False), ('{"selected_ids":null}', False),
])
def test_protocol(raw, valid):
    assert MODULE['valid_selection_output'](raw, [{'id':1}]) is valid
