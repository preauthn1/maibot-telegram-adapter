from datetime import datetime

from src.common.database.database import get_db_session
from src.common.database.database_model import ModelUsage
from src.common.logger import get_logger
from src.config.model_configs import ModelInfo
from src.llm_models.payload_content.context_item import ContextItem
from src.llm_models.vision_preprocessing import prepare_vision_messages

from .model_client.base_client import UsageRecord

logger = get_logger("消息压缩工具")


def compress_messages(items: list[ContextItem], img_target_size: int = 1 * 1024 * 1024) -> list[ContextItem]:
    """按 Base64 编码大小预算压缩重试图片，更新格式且不修改原消息。

    保留既有调用方的编码后预算语义；首次请求的原始字节预算由
    prepare_vision_messages 单独管理。
    """
    return prepare_vision_messages(items, max_bytes=(img_target_size // 4) * 3)


class LLMUsageRecorder:
    """
    LLM使用情况记录器
    """

    def __init__(self):
        pass

    @staticmethod
    def _calculate_input_cost(model_info: ModelInfo, model_usage: UsageRecord) -> float:
        """根据模型缓存配置计算输入 token 费用。"""

        prompt_tokens = model_usage.prompt_tokens or 0
        if not model_info.cache:
            return (prompt_tokens / 1000000) * model_info.price_in

        cache_hit_tokens = model_usage.prompt_cache_hit_tokens or 0
        cache_miss_tokens = model_usage.prompt_cache_miss_tokens or 0
        if cache_miss_tokens == 0 and cache_hit_tokens > 0:
            cache_miss_tokens = max(prompt_tokens - cache_hit_tokens, 0)
        if cache_hit_tokens + cache_miss_tokens == 0:
            cache_miss_tokens = prompt_tokens

        cached_cost = (cache_hit_tokens / 1000000) * model_info.cache_price_in
        uncached_cost = (cache_miss_tokens / 1000000) * model_info.price_in
        return cached_cost + uncached_cost

    def record_usage_to_database(
        self,
        model_info: ModelInfo,
        model_usage: UsageRecord,
        user_id: str,
        request_type: str,
        task_name: str | None = None,
        session_id: str = "",
        time_cost: float = 0.0,
    ):
        input_cost = self._calculate_input_cost(model_info, model_usage)
        output_cost = (model_usage.completion_tokens / 1000000) * model_info.price_out
        total_cost = round(input_cost + output_cost, 6)
        try:
            with get_db_session() as session:
                record = ModelUsage(
                    model_name=model_info.model_identifier,
                    model_assign_name=model_info.name,
                    model_api_provider_name=model_info.api_provider,
                    session_id=session_id.strip(),
                    task_name=task_name,
                    request_type=request_type,
                    time_cost=round(time_cost or 0.0, 3),
                    timestamp=datetime.now(),
                    prompt_tokens=model_usage.prompt_tokens or 0,
                    completion_tokens=model_usage.completion_tokens or 0,
                    total_tokens=model_usage.total_tokens or 0,
                    prompt_cache_enabled=bool(model_info.cache),
                    prompt_cache_hit_tokens=model_usage.prompt_cache_hit_tokens or 0,
                    prompt_cache_miss_tokens=model_usage.prompt_cache_miss_tokens or 0,
                    cost=total_cost or 0.0,
                )
                session.add(record)
            logger.debug(
                f"Token使用情况 - 模型: {model_usage.model_name}, "
                f"用户: {user_id}, 类型: {request_type}, "
                f"提示词: {model_usage.prompt_tokens}, 完成: {model_usage.completion_tokens}, "
                f"总计: {model_usage.total_tokens}"
            )
        except Exception as e:
            logger.error(f"记录token使用情况失败: {str(e)}")


llm_usage_recorder = LLMUsageRecorder()
