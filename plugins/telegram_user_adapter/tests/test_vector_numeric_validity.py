"""非法向量应在排序前显式失败，不产生 NaN 排名。"""
import numpy as np
import pytest
from src.chat.replyer.expression_vector_index import l2_normalize


@pytest.mark.parametrize('values', [
    [[float('nan'), 1.]], [[float('inf'), 1.]],
    [[float('-inf'), 1.]], [[0., 0.]], [[3e38, 3e38]],
])
def test_invalid_vector_rejected(values):
    with pytest.raises(ValueError):
        l2_normalize(np.array(values, dtype=np.float32))


def test_finite_vectors_keep_direction_and_input():
    values = np.array([[3., 4.], [0., 2.]], dtype=np.float32)
    original = values.copy()
    result = l2_normalize(values)
    np.testing.assert_allclose(result, [[.6, .8], [0., 1.]], rtol=1e-6)
    np.testing.assert_array_equal(values, original)
