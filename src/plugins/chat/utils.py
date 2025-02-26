import time
import random
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

def split_into_sentences(text: str) -> List[str]:
    """将文本分割成句子，但保持书名号中的内容完整
    
    Args:
        text: 要分割的文本字符串
        
    Returns:
        List[str]: 分割后的句子列表
    """
    delimiters = ['。', '！', '，', ',', '？', '…', '!', '?', '\n']  # 添加换行符作为分隔符
    remove_chars = ['，', ',']  # 只移除这两种逗号
    sentences = []
    current_sentence = ""
    in_book_title = False  # 标记是否在书名号内
    
    for char in text:
        current_sentence += char
        
        # 检查书名号
        if char == '《':
            in_book_title = True
        elif char == '》':
            in_book_title = False
        
        # 只有不在书名号内且是分隔符时才分割
        if char in delimiters and not in_book_title:
            if current_sentence.strip():  # 确保不是空字符串
                # 只移除逗号
                clean_sentence = current_sentence
                if clean_sentence[-1] in remove_chars:
                    clean_sentence = clean_sentence[:-1]
                if clean_sentence.strip():
                    sentences.append(clean_sentence.strip())
            current_sentence = ""
    
    # 处理最后一个句子
    if current_sentence.strip():
        # 如果最后一个字符是逗号，移除它
        if current_sentence[-1] in remove_chars:
            current_sentence = current_sentence[:-1]
        sentences.append(current_sentence.strip())
    
    # 过滤掉空字符串
    sentences = [s for s in sentences if s.strip()]
    
    return sentences

# 常见的错别字映射
TYPO_DICT = {
    '的': '地得',
    '了': '咯啦勒',
    '吗': '嘛麻',
    '吧': '八把罢',
    '是': '事',
    '在': '再在',
    '和': '合',
    '有': '又',
    '我': '沃窝喔',
    '你': '泥尼拟',
    '他': '它她塔祂',
    '们': '门',
    '啊': '阿哇',
    '呢': '呐捏',
    '都': '豆读毒',
    '很': '狠',
    '会': '回汇',
    '去': '趣取曲',
    '做': '作坐',
    '想': '相像',
    '说': '说税睡',
    '看': '砍堪刊',
    '来': '来莱赖',
    '好': '号毫豪',
    '给': '给既继',
    '过': '锅果裹',
    '能': '嫩',
    '为': '位未',
    '什': '甚深伸',
    '么': '末麽嘛',
    '话': '话花划',
    '知': '织直值',
    '道': '到',
    '听': '听停挺',
    '见': '见件建',
    '觉': '觉脚搅',
    '得': '得德锝',
    '着': '着找招',
    '像': '向象想',
    '等': '等灯登',
    '谢': '谢写卸',
    '对': '对队',
    '里': '里理鲤',
    '啦': '啦拉喇',
    '吃': '吃持迟',
    '哦': '哦喔噢',
    '呀': '呀压',
    '要': '药',
    '太': '太抬台',
    '快': '块',
    '点': '店',
    '以': '以已',
    '因': '因应',
    '啥': '啥沙傻',
    '行': '行型形',
    '哈': '哈蛤铪',
    '嘿': '嘿黑嗨',
    '嗯': '嗯恩摁',
    '哎': '哎爱埃',
    '呜': '呜屋污',
    '喂': '喂位未',
    '嘛': '嘛麻马',
    '嗨': '嗨害亥',
    '哇': '哇娃蛙',
    '咦': '咦意易',
    '嘻': '嘻西希'
}

def random_remove_punctuation(text: str) -> str:
    """随机处理标点符号，模拟人类打字习惯
    
    Args:
        text: 要处理的文本
        
    Returns:
        str: 处理后的文本
    """
    result = ''
    text_len = len(text)
    
    for i, char in enumerate(text):
        if char == '。' and i == text_len - 1:  # 结尾的句号
            if random.random() > 0.4:  # 80%概率删除结尾句号
                continue
        elif char == '，':
            rand = random.random()
            if rand < 0.25:  # 5%概率删除逗号
                continue
            elif rand < 0.25:  # 20%概率把逗号变成空格
                result += ' '
                continue
        result += char
    return result

def add_typos(text: str) -> str:
    """随机给文本添加错别字
    
    Args:
        text: 要处理的文本
        
    Returns:
        str: 添加错别字后的文本
    """
    TYPO_RATE = 0.02  # 控制错别字出现的概率(2%)
    
    result = ""
    for char in text:
        if char in TYPO_DICT and random.random() < TYPO_RATE:
            # 从可能的错别字中随机选择一个
            typos = TYPO_DICT[char]
            result += random.choice(typos)
        else:
            result += char
    return result

def process_text_with_typos(text: str) -> str:
    """处理文本，添加错别字和处理标点符号
    
    Args:
        text: 要处理的文本
        
    Returns:
        str: 处理后的文本
    """
    if random.random() < 0.9:  # 90%概率进行处理
        return random_remove_punctuation(add_typos(text))
    return text
