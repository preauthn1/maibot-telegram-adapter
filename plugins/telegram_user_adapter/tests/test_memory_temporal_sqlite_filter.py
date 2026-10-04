"""真实临时SQLite和段落时间过滤；候选列表合成，不调用向量模型。"""
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.retrieval.dual_path import DualPathRetriever, RetrievalResult
from src.A_memorix.core.utils.search_execution_service import SearchExecutionService
from src.A_memorix.core.utils.time_parser import parse_query_datetime_to_timestamp

@pytest.mark.parametrize('start,end,expected', [
    ('2026/01/10','2026/01/20', {'at_start','inside','at_end','overlap'}),
    ('2026/01/10',None, {'at_start','inside','at_end','after','overlap'}),
    (None,'2026/01/20', {'before','at_start','inside','at_end','overlap'}),
])
def test_real_sqlite_temporal_filter(tmp_path,start,end,expected):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        lower=parse_query_datetime_to_timestamp('2026/01/10')
        upper=parse_query_datetime_to_timestamp('2026/01/20',is_end=True)
        times={'before':lower-1,'at_start':lower,'inside':lower+60,'at_end':upper,'after':upper+1}
        rows=[]
        for name,stamp in times.items():
            h=store.add_paragraph('合成时间记录 '+name,time_meta={'event_time':stamp})
            assert store.get_paragraph(h)['event_time']==stamp
            rows.append(RetrievalResult(h,name,1.0,'paragraph','synthetic',{}))
        for name,meta in [('overlap',{'event_time_start':lower-60,'event_time_end':lower+60}),('unknown',None)]:
            h=store.add_paragraph('合成时间记录 '+name,time_meta=meta)
            rows.append(RetrievalResult(h,name,1.0,'paragraph','synthetic',{}))
        ok,temporal,error=SearchExecutionService._build_temporal(
            {'retrieval':{'temporal':{'allow_created_fallback':False}}},'hybrid',start,end,None,None)
        assert ok and not error and temporal is not None
        retriever=object.__new__(DualPathRetriever)
        retriever.metadata_store=store
        filtered=retriever._apply_temporal_filter_to_paragraphs(rows,temporal)
        assert {r.content for r in filtered}==expected
        assert all(r.metadata['time_meta']['match_basis']!='created_at_fallback' for r in filtered)
    finally:
        store.close()
