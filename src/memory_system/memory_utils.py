# -*- coding: utf-8 -*-
"""
记忆系统工具函数
包含模糊查找、相似度计算等工具函数
"""
import json
import re
from difflib import SequenceMatcher

from src.common.logger import get_logger


logger = get_logger("memory_utils")

def parse_md_json(json_text: str) -> list[str]:
    """从Markdown格式的内容中提取JSON对象和推理内容"""
    json_objects = []
    reasoning_content = ""

    # 使用正则表达式查找```json包裹的JSON内容
    json_pattern = r"```json\s*(.*?)\s*```"
    matches = re.findall(json_pattern, json_text, re.DOTALL)

    # 提取JSON之前的内容作为推理文本
    if matches:
        # 找到第一个```json的位置
        first_json_pos = json_text.find("```json")
        if first_json_pos > 0:
            reasoning_content = json_text[:first_json_pos].strip()
            # 清理推理内容中的注释标记
            reasoning_content = re.sub(r"^//\s*", "", reasoning_content, flags=re.MULTILINE)
            reasoning_content = reasoning_content.strip()

    for match in matches:
        try:
            # 清理可能的注释和格式问题
            json_str = re.sub(r"//.*?\n", "\n", match)  # 移除单行注释
            json_str = re.sub(r"/\*.*?\*/", "", json_str, flags=re.DOTALL)  # 移除多行注释
            if json_str := json_str.strip():
                json_obj = json.loads(json_str)
                if isinstance(json_obj, dict):
                    json_objects.append(json_obj)
                elif isinstance(json_obj, list):
                    for item in json_obj:
                        if isinstance(item, dict):
                            json_objects.append(item)
        except Exception as e:
            logger.warning(f"解析JSON块失败: {e}, 块内容: {match[:100]}...")
            continue

    return json_objects, reasoning_content

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

