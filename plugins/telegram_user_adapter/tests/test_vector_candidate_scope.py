"""真实索引过滤器验证归属和内容新鲜度；不调用 embedding。"""
from types import SimpleNamespace
from src.chat.replyer.expression_vector_index import ExpressionVectorIndex, IndexedExpression, expression_fingerprint


def test_filter_excludes_other_scope_stale_content_and_profile():
    def entry(i, marker='active', dimension=2):
        return IndexedExpression(i, '倾诉', '简短共情', 1,
            expression_fingerprint(i, '倾诉', '简短共情'), marker, 'synthetic', dimension, 0, i)
    snapshot = SimpleNamespace(expressions=[entry(1), entry(2), entry(3), entry(4, 'old'), entry(5, dimension=3)])
    scoped = [dict(id=i, situation='倾诉', style='已修改' if i == 3 else '简短共情') for i in (1,3,4,5)]
    result = ExpressionVectorIndex._filter_indexed_expressions(snapshot, scoped, SimpleNamespace(marker='active', dimension=2))
    assert [item.id for item in result] == [1]
