import time
from typing import List
from .message import Message
import requests
import numpy as np
from .config import llm_config

def combine_messages(messages: List[Message]) -> str:
    """将消息列表组合成格式化的字符串
    
    Args:
        messages: Message对象列表
        
    Returns:
        str: 格式化后的消息字符串
    """
    result = ""
    for message in messages:
        time_str = time.strftime("%m-%d %H:%M:%S", time.localtime(message.time))
        name = message.user_nickname or f"用户{message.user_id}"
        content = message.processed_plain_text or message.plain_text
        
        result += f"[{time_str}] {name}: {content}\n"
        
    return result

def is_mentioned_bot_in_message(message: Message) -> bool:
    """检查消息是否提到了机器人"""
    keywords = ['麦麦', '麦哲伦']
    for keyword in keywords:
        if keyword in message.processed_plain_text:
            return True
    return False

def is_mentioned_bot_in_txt(message: str) -> bool:
    """检查消息是否提到了机器人"""
    keywords = ['麦麦', '麦哲伦']
    for keyword in keywords:
        if keyword in message:
            return True
    return False

def get_embedding(text):
    url = "https://api.siliconflow.cn/v1/embeddings"
    payload = {
        "model": "BAAI/bge-m3",
        "input": text,
        "encoding_format": "float"
    }
    headers = {
        "Authorization": f"Bearer {llm_config.SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }
    
    response = requests.request("POST", url, json=payload, headers=headers)
    
    if response.status_code != 200:
        print(f"API请求失败: {response.status_code}")
        print(f"错误信息: {response.text}")
        return None
        
    return response.json()['data'][0]['embedding']

def cosine_similarity(v1, v2):
    dot_product = np.dot(v1, v2)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    return dot_product / (norm1 * norm2)

def get_recent_group_messages(db, group_id: int, limit: int = 12) -> list:
    """从数据库获取群组最近的消息记录
    
    Args:
        db: Database实例
        group_id: 群组ID
        limit: 获取消息数量，默认12条
        
    Returns:
        list: Message对象列表，按时间正序排列
    """

        # 从数据库获取最近消息
    recent_messages = list(db.db.messages.find(
        {"group_id": group_id},
        {
            "time": 1,
            "user_id": 1,
            "user_nickname": 1,
            "message_id": 1,
            "raw_message": 1,
            "processed_text": 1
        }
    ).sort("time", -1).limit(limit))

    if not recent_messages:
        return []
        
    # 转换为 Message对象列表
    from .message import Message
    message_objects = []
    for msg_data in recent_messages:
        msg = Message(
            time=msg_data["time"],
            user_id=msg_data["user_id"],
            user_nickname=msg_data.get("user_nickname", ""),
            message_id=msg_data["message_id"],
            raw_message=msg_data["raw_message"],
            processed_plain_text=msg_data.get("processed_text", ""),
            group_id=group_id
        )
        message_objects.append(msg)
    
    # 按时间正序排列
    message_objects.reverse()
    return message_objects
