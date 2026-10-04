import sys
from pathlib import Path
from copy import deepcopy
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[3]/'scripts'))
from sender_probe_inputs import build_pair

TAG='<sender sender_id="17" sender_platform="telegram" />\n'

@pytest.mark.parametrize('content,role', [('question','user'),(TAG+TAG+'question','user'),(TAG+'question','assistant')])
def test_invalid_target_rejected(content,role):
    with pytest.raises(ValueError):
        build_pair({'messages':[{'role':role,'content':content}]})


def test_pair_preserves_source_and_only_removes_target_tag():
    original={'messages':[{'role':'user','content':'history'}, {'role':'user','content':'time\n'+TAG+'question'}]}
    saved=deepcopy(original)
    pair=build_pair(original)
    assert original==saved
    assert pair['assembled']==original['messages']
    assert pair['without_target_identity']==[{'role':'user','content':'history'},{'role':'user','content':'time\nquestion'}]
    pair['without_target_identity'][0]['content']='changed'
    assert original==saved and pair['assembled']==saved['messages']
