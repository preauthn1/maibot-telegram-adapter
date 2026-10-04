"""两批候选抽样应互斥，不浪费原有名额。"""
from src.chat.replyer import maisaka_expression_selector as module


def test_high_and_second_batch_are_disjoint(monkeypatch):
    candidates = [dict(id=i, situation='测试', style='表达', count=2) for i in range(12)]
    calls = []
    def sample(population, k):
        calls.append([c['id'] for c in population])
        return population[:k]
    monkeypatch.setattr(module, 'weighted_sample', sample)
    selector = object.__new__(module.MaisakaExpressionSelector)
    result = selector._sample_legacy_expression_candidates(candidates)
    assert len(result) == 10
    assert not set(calls[1]).intersection(calls[0][:5])
    assert len({c['id'] for c in result}) == 10
    assert len(candidates) == 12


def test_single_batch_and_small_pool_preserved(monkeypatch):
    monkeypatch.setattr(module, 'weighted_sample', lambda population,k: population[:k])
    selector = object.__new__(module.MaisakaExpressionSelector)
    candidates = [dict(id=i, count=1) for i in range(12)]
    assert len(selector._sample_legacy_expression_candidates(candidates)) == 5
    assert selector._sample_legacy_expression_candidates(candidates[:9]) == []
