"""任务枚举保持兼容且不访问已弃用的实例元数据。"""
import warnings
from src.services import service_task_resolver as module
from src.config.model_configs import TaskConfig


def test_task_enumeration_has_no_deprecated_metadata_access():
    models = module.config_manager.get_model_config().model_task_config
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        expected = {name: getattr(models, name) for name in dir(models)
                    if not name.startswith('__') and isinstance(getattr(models, name), TaskConfig)}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        actual = module.get_available_models()
    assert list(actual) == list(expected)
    assert all(actual[name] is expected[name] for name in expected)
    assert not [w for w in caught if 'instance is deprecated' in str(w.message)]
