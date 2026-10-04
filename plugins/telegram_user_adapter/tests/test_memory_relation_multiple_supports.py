"""真实SQLite多支撑重校验：时间、来源切换及批量查询边界。"""
from unittest.mock import Mock
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.retrieval.dual_path import DualPathRetriever, RetrievalResult, TemporalQueryOptions


def test_multiple_supports_revalidate_without_dropping_valid_relation(tmp_path, monkeypatch):
    store = MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        p1 = store.add_paragraph('合成早期来源A', source='synthetic-A', time_meta={'event_time':100.0})
        p2 = store.add_paragraph('合成后期来源B', source='synthetic-B', time_meta={'event_time':250.0})
        relation = store.add_relation('合成甲','访问','合成乙', source_paragraph=p1)
        assert store.link_paragraph_relation(p2, relation)
        retriever = object.__new__(DualPathRetriever)
        retriever.metadata_store = store
        read_batch = Mock(wraps=store.get_paragraphs_by_relation_hashes)
        monkeypatch.setattr(store, 'get_paragraphs_by_relation_hashes', read_batch)
        item = RetrievalResult(relation,'合成关系',1.0,'relation','synthetic',{})
        duplicate = RetrievalResult(relation,'同一关系的另一候选',0.5,'relation','synthetic',{})
        early = TemporalQueryOptions(time_from=90,time_to=110,allow_created_fallback=False)
        late = TemporalQueryOptions(time_from=200,time_to=300,allow_created_fallback=False)
        assert retriever._apply_temporal_filter_to_relations([item,duplicate],early)==[item,duplicate]
        read_batch.assert_called_once_with([relation])
        assert item.metadata['time_meta']['effective_end']==100.0
        read_batch.reset_mock()
        assert retriever._apply_temporal_filter_to_relations([item,duplicate],late)==[item,duplicate]
        read_batch.assert_called_once_with([relation])
        assert all(r.metadata['time_meta']['effective_end']==250.0 for r in (item,duplicate))
        # 时间内有B支撑，但指定A时不能复用之前的B时间元数据。
        source_a = TemporalQueryOptions(time_from=200,time_to=300,source='synthetic-A',allow_created_fallback=False)
        assert retriever._apply_temporal_filter_to_relations([item],source_a)==[]
        assert 'time_meta' not in item.metadata
        source_b = TemporalQueryOptions(time_from=200,time_to=300,source='synthetic-B',allow_created_fallback=False)
        assert retriever._apply_temporal_filter_to_relations([item],source_b)==[item]
        assert item.metadata['time_meta']['effective_end']==250.0
    finally:
        store.close()
