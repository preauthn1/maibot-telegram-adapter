# -*- coding: utf-8 -*-
"""
记忆系统工具函数
包含模糊查找、相似度计算等工具函数
"""
import re
from difflib import SequenceMatcher
from typing import List, Tuple, Optional

from src.common.database.database_model import MemoryChest as MemoryChestModel
from src.common.logger import get_logger

logger = get_logger("memory_utils")


def calculate_similarity(text1: str, text2: str) -> float:
    """
    计算两个文本的相似度
    
    Args:
        text1: 第一个文本
        text2: 第二个文本
        
    Returns:
        float: 相似度分数 (0-1)
    """
    try:
        # 预处理文本
        text1 = preprocess_text(text1)
        text2 = preprocess_text(text2)
        
        # 使用SequenceMatcher计算相似度
        similarity = SequenceMatcher(None, text1, text2).ratio()
        
        # 如果其中一个文本包含另一个，提高相似度
        if text1 in text2 or text2 in text1:
            similarity = max(similarity, 0.8)
        
        return similarity
        
    except Exception as e:
        logger.error(f"计算相似度时出错: {e}")
        return 0.0


def preprocess_text(text: str) -> str:
    """
    预处理文本，提高匹配准确性
    
    Args:
        text: 原始文本
        
    Returns:
        str: 预处理后的文本
    """
    try:
        # 转换为小写
        text = text.lower()
        
        # 移除标点符号和特殊字符
        text = re.sub(r'[^\w\s]', '', text)
        
        # 移除多余空格
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text
        
    except Exception as e:
        logger.error(f"预处理文本时出错: {e}")
        return text


def fuzzy_find_memory_by_title(target_title: str, similarity_threshold: float = 0.9) -> List[Tuple[str, str, float]]:
    """
    根据标题模糊查找记忆
    
    Args:
        target_title: 目标标题
        similarity_threshold: 相似度阈值，默认0.9
        
    Returns:
        List[Tuple[str, str, float]]: 匹配的记忆列表，每个元素为(title, content, similarity_score)
    """
    try:
        # 获取所有记忆
        all_memories = MemoryChestModel.select()
        
        matches = []
        for memory in all_memories:
            similarity = calculate_similarity(target_title, memory.title)
            if similarity >= similarity_threshold:
                matches.append((memory.title, memory.content, similarity))
        
        # 按相似度降序排序
        matches.sort(key=lambda x: x[2], reverse=True)
        
        logger.info(f"模糊查找标题 '{target_title}' 找到 {len(matches)} 个匹配项")
        return matches
        
    except Exception as e:
        logger.error(f"模糊查找记忆时出错: {e}")
        return []


def find_best_matching_memory(target_title: str, similarity_threshold: float = 0.9) -> Optional[Tuple[str, str, float]]:
    """
    查找最佳匹配的记忆
    
    Args:
        target_title: 目标标题
        similarity_threshold: 相似度阈值
        
    Returns:
        Optional[Tuple[str, str, float]]: 最佳匹配的记忆(title, content, similarity)或None
    """
    try:
        matches = fuzzy_find_memory_by_title(target_title, similarity_threshold)
        
        if matches:
            best_match = matches[0]  # 已经按相似度排序，第一个是最佳匹配
            logger.info(f"找到最佳匹配: '{best_match[0]}' (相似度: {best_match[2]:.3f})")
            return best_match
        else:
            logger.info(f"未找到相似度 >= {similarity_threshold} 的记忆")
            return None
            
    except Exception as e:
        logger.error(f"查找最佳匹配记忆时出错: {e}")
        return None


def check_title_exists_fuzzy(target_title: str, similarity_threshold: float = 0.9) -> bool:
    """
    检查标题是否已存在（模糊匹配）
    
    Args:
        target_title: 目标标题
        similarity_threshold: 相似度阈值，默认0.9（较高阈值避免误判）
        
    Returns:
        bool: 是否存在相似标题
    """
    try:
        matches = fuzzy_find_memory_by_title(target_title, similarity_threshold)
        exists = len(matches) > 0
        
        if exists:
            logger.info(f"发现相似标题: '{matches[0][0]}' (相似度: {matches[0][2]:.3f})")
        else:
            logger.debug("未发现相似标题")
            
        return exists
        
    except Exception as e:
        logger.error(f"检查标题是否存在时出错: {e}")
        return False
