"""
根据时间或关键词在chat_history中查询 - 工具实现
从ChatHistory表的聊天记录概述库中查询
"""

import json
from typing import Optional
from src.common.logger import get_logger
from src.config.config import model_config
from src.common.database.database_model import ChatHistory
from src.llm_models.utils_model import LLMRequest
from src.chat.utils.utils import parse_keywords_string
from .tool_registry import register_memory_retrieval_tool
from .tool_utils import parse_datetime_to_timestamp, parse_time_range

logger = get_logger("memory_retrieval_tools")


async def query_chat_history(
    chat_id: str,
    keyword: Optional[str] = None,
    time_range: Optional[str] = None
) -> str:
    """根据时间或关键词在chat_history表中查询聊天记录概述
    
    Args:
        chat_id: 聊天ID
        keyword: 关键词（可选，支持多个关键词，可用空格、逗号等分隔）
        time_range: 时间范围或时间点，格式：
            - 时间范围："YYYY-MM-DD HH:MM:SS - YYYY-MM-DD HH:MM:SS"
            - 时间点："YYYY-MM-DD HH:MM:SS"（查询包含该时间点的记录）
        
    Returns:
        str: 查询结果
    """
    try:
        # 检查参数
        if not keyword and not time_range:
            return "未指定查询参数（需要提供keyword或time_range之一）"
        
        # 构建查询条件
        query = ChatHistory.select().where(ChatHistory.chat_id == chat_id)
        
        # 时间过滤条件
        if time_range:
            # 判断是时间点还是时间范围
            if " - " in time_range:
                # 时间范围：查询与时间范围有交集的记录
                start_timestamp, end_timestamp = parse_time_range(time_range)
                # 交集条件：start_time < end_timestamp AND end_time > start_timestamp
                time_filter = (
                    (ChatHistory.start_time < end_timestamp) &
                    (ChatHistory.end_time > start_timestamp)
                )
            else:
                # 时间点：查询包含该时间点的记录（start_time <= time_point <= end_time）
                target_timestamp = parse_datetime_to_timestamp(time_range)
                time_filter = (
                    (ChatHistory.start_time <= target_timestamp) &
                    (ChatHistory.end_time >= target_timestamp)
                )
            query = query.where(time_filter)
        
        # 执行查询
        records = list(query.order_by(ChatHistory.start_time.desc()).limit(50))
        
        if not records:
            return "未找到相关聊天记录概述"
        
        # 如果有关键词，进一步过滤
        if keyword:
            # 解析多个关键词（支持空格、逗号等分隔符）
            keywords_list = parse_keywords_string(keyword)
            if not keywords_list:
                keywords_list = [keyword.strip()] if keyword.strip() else []
            
            # 转换为小写以便匹配
            keywords_lower = [kw.lower() for kw in keywords_list if kw.strip()]
            
            if not keywords_lower:
                return "关键词为空"
            
            filtered_records = []
            
            for record in records:
                # 在theme、keywords、summary、original_text中搜索
                theme = (record.theme or "").lower()
                summary = (record.summary or "").lower()
                original_text = (record.original_text or "").lower()
                
                # 解析record中的keywords JSON
                record_keywords_list = []
                if record.keywords:
                    try:
                        keywords_data = json.loads(record.keywords) if isinstance(record.keywords, str) else record.keywords
                        if isinstance(keywords_data, list):
                            record_keywords_list = [str(k).lower() for k in keywords_data]
                    except (json.JSONDecodeError, TypeError, ValueError):
                        pass
                
                # 检查是否包含任意一个关键词（OR关系）
                matched = False
                for kw in keywords_lower:
                    if (kw in theme or 
                        kw in summary or 
                        kw in original_text or
                        any(kw in k for k in record_keywords_list)):
                        matched = True
                        break
                
                if matched:
                    filtered_records.append(record)
            
            if not filtered_records:
                keywords_str = "、".join(keywords_list)
                return f"未找到包含关键词'{keywords_str}'的聊天记录概述"
            
            records = filtered_records
        
        # 构建结果文本
        results = []
        for record in records[:10]:  # 最多返回10条记录
            result_parts = []
            
            # 添加主题
            if record.theme:
                result_parts.append(f"主题：{record.theme}")
            
            # 添加时间范围
            from datetime import datetime
            start_str = datetime.fromtimestamp(record.start_time).strftime("%Y-%m-%d %H:%M:%S")
            end_str = datetime.fromtimestamp(record.end_time).strftime("%Y-%m-%d %H:%M:%S")
            result_parts.append(f"时间：{start_str} - {end_str}")
            
            # 添加概括（优先使用summary，如果没有则使用original_text的前200字符）
            if record.summary:
                result_parts.append(f"概括：{record.summary}")
            elif record.original_text:
                text_preview = record.original_text[:200]
                if len(record.original_text) > 200:
                    text_preview += "..."
                result_parts.append(f"内容：{text_preview}")
            
            results.append("\n".join(result_parts))
        
        if not results:
            return "未找到相关聊天记录概述"
        
        # 如果只有一条记录，直接返回
        if len(results) == 1:
            return results[0]
        
        # 多条记录，使用LLM总结
        try:
            llm_request = LLMRequest(
                model_set=model_config.model_task_config.utils_small,
                request_type="chat_history_analysis"
            )
            
            query_desc = []
            if keyword:
                # 解析关键词列表用于显示
                keywords_list = parse_keywords_string(keyword)
                if keywords_list:
                    keywords_str = "、".join(keywords_list)
                    query_desc.append(f"关键词：{keywords_str}")
                else:
                    query_desc.append(f"关键词：{keyword}")
            if time_range:
                if " - " in time_range:
                    query_desc.append(f"时间范围：{time_range}")
                else:
                    query_desc.append(f"时间点：{time_range}")
            
            query_info = "，".join(query_desc) if query_desc else "聊天记录概述"
            
            combined_results = "\n\n---\n\n".join(results)
            
            analysis_prompt = f"""请根据以下聊天记录概述，总结与查询条件相关的信息。请输出一段平文本，不要有特殊格式。
查询条件：{query_info}

聊天记录概述：
{combined_results}

请仔细分析聊天记录概述，提取与查询条件相关的信息并给出总结。如果概述中没有相关信息，输出"无有效信息"即可，不要输出其他内容。

总结："""
            
            response, (reasoning, model_name, tool_calls) = await llm_request.generate_response_async(
                prompt=analysis_prompt,
                temperature=0.3,
                max_tokens=512
            )
            
            logger.info(f"查询聊天历史概述提示词: {analysis_prompt}")
            logger.info(f"查询聊天历史概述响应: {response}")
            logger.info(f"查询聊天历史概述推理: {reasoning}")
            logger.info(f"查询聊天历史概述模型: {model_name}")
            
            if "无有效信息" in response:
                return "无有效信息"
            
            return response
            
        except Exception as llm_error:
            logger.error(f"LLM分析聊天记录概述失败: {llm_error}")
            # 如果LLM分析失败，返回前3条记录的摘要
            return "\n\n---\n\n".join(results[:3])
            
    except Exception as e:
        logger.error(f"查询聊天历史概述失败: {e}")
        return f"查询失败: {str(e)}"


def register_tool():
    """注册工具"""
    register_memory_retrieval_tool(
        name="query_chat_history",
        description="根据时间或关键词在chat_history表的聊天记录概述库中查询。可以查询某个时间点发生了什么、某个时间范围内的事件，或根据关键词搜索消息概述",
        parameters=[
            {
                "name": "keyword",
                "type": "string",
                "description": "关键词（可选，支持多个关键词，可用空格、逗号、斜杠等分隔，如：'麦麦 百度网盘' 或 '麦麦,百度网盘'。用于在主题、关键词、概括、原文中搜索，只要包含任意一个关键词即匹配）",
                "required": False
            },
            {
                "name": "time_range",
                "type": "string",
                "description": "时间范围或时间点（可选）。格式：'YYYY-MM-DD HH:MM:SS - YYYY-MM-DD HH:MM:SS'（时间范围，查询与时间范围有交集的记录）或 'YYYY-MM-DD HH:MM:SS'（时间点，查询包含该时间点的记录）",
                "required": False
            }
        ],
        execute_func=query_chat_history
    )
