import pytest
from src.maisaka.chat_loop_service import MaisakaChatLoopService

@pytest.mark.parametrize('value, expected', [(0, 0), (12, 12), ('0', 0), ('12', 12), (12.0, 12)])
def test_valid_usage_conversion(value, expected):
    assert MaisakaChatLoopService._coerce_int(value, 99) == expected
