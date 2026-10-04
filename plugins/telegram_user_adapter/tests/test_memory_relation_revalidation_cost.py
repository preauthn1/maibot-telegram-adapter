"""合成SQLite成本探针；计时不设跨机器阈值，不代表生产性能。"""
import json
import statistics
import time
import pytest
from src.A_memorix.core.storage.metadata_store import MetadataStore
from src.A_memorix.core.retrieval.dual_path import DualPathRetriever, RetrievalResult, TemporalQueryOptions

@pytest.mark.parametrize('count', [20, 100])
def test_revalidation_cost(tmp_path, record_property, count):
    store=MetadataStore(data_dir=tmp_path)
    store.connect()
    try:
        rows=[]
        for index in range(count):
            early=store.add_paragraph(f'合成早期支撑{index}',time_meta={'event_time':100.0})
            late=store.add_paragraph(f'合成后期支撑{index}',time_meta={'event_time':250.0})
            relation=store.add_relation(f'合成人物{index}','访问','合成地点',source_paragraph=early)
            assert store.link_paragraph_relation(late,relation)
            rows.append(RetrievalResult(relation,f'合成关系{index}',1.0,'relation','synthetic',{}))
        retriever=object.__new__(DualPathRetriever)
        retriever.metadata_store=store
        window=TemporalQueryOptions(time_from=200,time_to=300,allow_created_fallback=False)
        # 先暖机，随后候选均带旧time_meta；必须仍重新读取支撑。
        assert len(retriever._apply_temporal_filter_to_relations(rows,window))==count
        elapsed=[]
        sql_counts=[]
        for _ in range(10):
            selects=[]
            store._conn.set_trace_callback(lambda sql: selects.append(1) if sql.lstrip().upper().startswith('SELECT') else None)
            started=time.perf_counter()
            filtered=retriever._apply_temporal_filter_to_relations(rows,window)
            elapsed.append((time.perf_counter()-started)*1000)
            store._conn.set_trace_callback(None)
            sql_counts.append(len(selects))
            assert len(filtered)==count
            assert all(r.metadata['time_meta']['effective_end']==250.0 for r in filtered)
        record_property('synthetic_revalidation_cost',json.dumps({'relations':count,'supports':count*2,'runs':10,'median_ms':statistics.median(elapsed),'max_ms':max(elapsed),'select_counts':sql_counts,'scope':'warm synthetic SQLite; no vector recall; trace overhead included; no old-version comparison'}))
    finally:
        store._conn.set_trace_callback(None)
        store.close()
