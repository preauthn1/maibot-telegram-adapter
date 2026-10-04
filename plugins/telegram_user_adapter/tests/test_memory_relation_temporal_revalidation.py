"""真实SQLite支撑关系；合成候选跨窗口复用不能绕过重新校验。"""
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.retrieval.dual_path import DualPathRetriever, RetrievalResult, TemporalQueryOptions


def test_relation_reused_across_windows(tmp_path):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        paragraph=store.add_paragraph('合成：甲在时间100访问乙',time_meta={'event_time':100.0})
        relation=store.add_relation('合成甲','访问','合成乙',source_paragraph=paragraph)
        retriever=object.__new__(DualPathRetriever)
        retriever.metadata_store=store
        item=RetrievalResult(relation,'合成关系',1.0,'relation','synthetic',{})
        first=TemporalQueryOptions(time_from=90,time_to=110,allow_created_fallback=False)
        second=TemporalQueryOptions(time_from=200,time_to=300,allow_created_fallback=False)
        assert retriever._apply_temporal_filter_to_relations([item],first)==[item]
        assert item.metadata['time_meta']['effective_end']==100.0
        assert retriever._apply_temporal_filter_to_relations([item],second)==[]
    finally:
        store.close()
