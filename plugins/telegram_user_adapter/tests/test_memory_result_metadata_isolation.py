"""合成payload来源信息隔离，不访问后端。"""
from copy import deepcopy
from src.services.memory_service import memory_service


def test_search_coercion_does_not_mutate_source_payload():
    payload={'hits':[{'content':'合成事实','metadata':{'source':{'ids':['a']}},'rank':1,'source_branches':['lexical']}]}
    before=deepcopy(payload)
    result=memory_service._coerce_search_result(payload)
    assert payload==before
    assert result.hits[0].metadata['rank']==1
    assert result.hits[0].metadata['source_branches']==['lexical']


def test_nested_metadata_does_not_alias_between_consumers():
    payload={'hits':[{'content':'合成事实','metadata':{'source':{'ids':['a']}},'source_branches':['lexical']}]}
    first=memory_service._coerce_search_result(payload)
    second=memory_service._coerce_search_result(payload)
    first.hits[0].metadata['source']['ids'].append('changed')
    first.hits[0].metadata['source_branches'].append('changed')
    assert payload['hits'][0]['metadata']=={'source':{'ids':['a']}}
    assert payload['hits'][0]['source_branches']==['lexical']
    assert second.hits[0].metadata['source']['ids']==['a']
    assert second.hits[0].metadata['source_branches']==['lexical']
