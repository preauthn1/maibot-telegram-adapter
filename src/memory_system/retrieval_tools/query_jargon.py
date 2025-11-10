"""
根据关键词在jargon库中查询 - 工具实现
"""

from src.common.logger import get_logger
from src.jargon.jargon_miner import search_jargon
from .tool_registry import register_memory_retrieval_tool

logger = get_logger("memory_retrieval_tools")


async def query_jargon(
    keyword: str, 
    chat_id: str,
    fuzzy: bool = False
) -> str:
    """根据关键词在jargon库中查询
    
    Args:
        keyword: 关键词（黑话/俚语/缩写）
        chat_id: 聊天ID
        fuzzy: 是否使用模糊搜索，默认False（精确匹配）
        
    Returns:
        str: 查询结果
    """
    try:
        content = str(keyword).strip()
        if not content:
            return "关键词为空"
        
        # 执行搜索（仅搜索当前会话或全局）
        results = search_jargon(
            keyword=content,
            chat_id=chat_id,
            limit=1,
            case_sensitive=False,
            fuzzy=fuzzy
        )
        
        if results:
            result = results[0]
            translation = result.get("translation", "").strip()
            meaning = result.get("meaning", "").strip()
            search_type = "模糊搜索" if fuzzy else "精确匹配"
            output = f'"{content}可能为黑话或者网络简写，翻译为：{translation}，含义为：{meaning}"'
            logger.info(f"在jargon库中找到匹配（当前会话或全局，{search_type}）: {content}")
            return output
        
        # 未命中
        search_type = "模糊搜索" if fuzzy else "精确匹配"
        logger.info(f"在jargon库中未找到匹配（当前会话或全局，{search_type}）: {content}")
        return f"未在jargon库中找到'{content}'的解释"
        
    except Exception as e:
        logger.error(f"查询jargon失败: {e}")
        return f"查询失败: {str(e)}"


def register_tool():
    """注册工具"""
    register_memory_retrieval_tool(
        name="query_jargon",
        description="根据关键词在jargon库中查询黑话/俚语/缩写的含义。支持大小写不敏感搜索和模糊搜索。仅搜索当前会话或全局jargon。",
        parameters=[
            {
                "name": "keyword",
                "type": "string",
                "description": "关键词（黑话/俚语/缩写），支持模糊搜索",
                "required": True
            },
            {
                "name": "fuzzy",
                "type": "boolean",
                "description": "是否使用模糊搜索（部分匹配），默认False（精确匹配）。当精确匹配找不到时，可以尝试使用模糊搜索。",
                "required": False
            }
        ],
        execute_func=query_jargon
    )

