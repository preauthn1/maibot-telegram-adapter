from datetime import datetime

from src.common.database.database import get_db_session
from src.common.database.database_model import ModelUsage
from src.common.logger import get_logger
from src.config.model_configs import ModelInfo, ModelPricePeriod
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


# 供应商在响应中上报过 Prompt 缓存用量的模型，按 (api_provider, model_identifier) 记住。
# 部分供应商（如 StepFun）只在命中时返回缓存字段，首次命中前该模型的用量不计入缓存统计；
# 进程重启后集合清空，出现命中后自动恢复，无需任何配置。
_CACHE_REPORTING_MODELS: set[tuple[str, str]] = set()


class LLMUsageRecorder:
    """
    LLM使用情况记录器
    """

    def __init__(self):
        pass

    @staticmethod
    def _resolve_prices(model_info: ModelInfo, request_started_at: datetime) -> ModelInfo | ModelPricePeriod:
        """按请求开始的本地时间选择一整组单价。"""

        local_time = request_started_at.astimezone().strftime("%H:%M")
        for period in model_info.price_periods:
            if period.start_time < period.end_time:
                matches = period.start_time <= local_time < period.end_time
            else:
                matches = local_time >= period.start_time or local_time < period.end_time
            if matches:
                return period
        return model_info

    @staticmethod
    def _calculate_input_cost(
        model_info: ModelInfo,
        model_usage: UsageRecord,
        prices: ModelInfo | ModelPricePeriod | None = None,
    ) -> float:
        """计算输入 token 费用，区分缓存命中与未命中部分。

        缓存命中部分按当前档位的 cache_price_in 计费，该值为 0 即命中免费；
        未命中部分按 price_in 计费。供应商未返回缓存用量时全部按 price_in 计费。
        """

        if prices is None:
            prices = model_info
        prompt_tokens = model_usage.prompt_tokens or 0

        cache_hit_tokens = model_usage.prompt_cache_hit_tokens or 0
        cache_miss_tokens = model_usage.prompt_cache_miss_tokens or 0
        if cache_miss_tokens == 0 and cache_hit_tokens > 0:
            cache_miss_tokens = max(prompt_tokens - cache_hit_tokens, 0)
        if cache_hit_tokens + cache_miss_tokens == 0:
            cache_miss_tokens = prompt_tokens

        cached_cost = (cache_hit_tokens / 1000000) * prices.cache_price_in
        uncached_cost = (cache_miss_tokens / 1000000) * prices.price_in
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
        *,
        request_started_at: datetime,
    ):
        recorded_at = datetime.now()
        prices = self._resolve_prices(model_info, request_started_at)
        input_cost = self._calculate_input_cost(model_info, model_usage, prices)
        output_cost = (model_usage.completion_tokens / 1000000) * prices.price_out
        total_cost = round(input_cost + output_cost, 6)
        cache_model_key = (model_info.api_provider, model_info.model_identifier)
        if model_usage.prompt_cache_reported:
            _CACHE_REPORTING_MODELS.add(cache_model_key)
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
                    timestamp=recorded_at,
                    prompt_tokens=model_usage.prompt_tokens or 0,
                    completion_tokens=model_usage.completion_tokens or 0,
                    total_tokens=model_usage.total_tokens or 0,
                    # 是否展示缓存统计由服务商行为自动探测，与价格配置无关：
                    # 本次响应上报了缓存字段，或该模型此前上报过（零命中时部分供应商不返回字段，
                    # 记住之后这些调用按全部未命中计入统计）。
                    prompt_cache_enabled=(
                        model_usage.prompt_cache_reported or cache_model_key in _CACHE_REPORTING_MODELS
                    ),
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
