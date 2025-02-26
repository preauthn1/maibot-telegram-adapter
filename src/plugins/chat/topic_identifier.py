from typing import Optional, Dict, List
from openai import OpenAI
from .message import Message
from .config import global_config, llm_config
import jieba

class TopicIdentifier:
    def __init__(self):
        self.client = OpenAI(
            api_key=llm_config.SILICONFLOW_API_KEY,
            base_url=llm_config.SILICONFLOW_BASE_URL
        )
        
    def identify_topic_llm(self, text: str) -> Optional[str]:
        """识别消息主题"""

        prompt = f"""判断这条消息的主题，如果没有明显主题请回复"无主题"，要求：
1. 主题通常2-4个字，必须简短，要求精准概括，不要太具体。
2. 建议给出多个主题，之间用英文逗号分割。只输出主题本身就好，不要有前后缀。

消息内容：{text}"""

        response = self.client.chat.completions.create(
            model="Pro/deepseek-ai/DeepSeek-V3",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=10
        )
        
        if not response or not response.choices:
            print(f"\033[1;31m[错误]\033[0m OpenAI API 返回为空")
            return None
            
        # 从 OpenAI API 响应中获取第一个选项的消息内容,并去除首尾空白字符
        topic = response.choices[0].message.content.strip() if response.choices[0].message.content else None
        
        if topic == "无主题":
            return None
        else:
            # print(f"[主题分析结果]{text[:20]}... : {topic}")
            split_topic = self.parse_topic(topic)
            return split_topic


    def parse_topic(self, topic: str) -> List[str]:
        """解析主题，返回主题列表"""
        if not topic or topic == "无主题":
            return []
        return [t.strip() for t in topic.split(",") if t.strip()]

    def identify_topic_jieba(self, text: str) -> Optional[str]:
        """使用jieba识别主题"""
        words = jieba.lcut(text)
        # 去除停用词和标点符号
        stop_words = {
            '的', '了', '和', '是', '就', '都', '而', '及', '与', '这', '那', '但', '然', '却', 
            '因为', '所以', '如果', '虽然', '一个', '我', '你', '他', '她', '它', '我们', '你们', 
            '他们', '在', '有', '个', '把', '被', '让', '给', '从', '向', '到', '又', '也', '很', 
            '啊', '吧', '呢', '吗', '呀', '哦', '哈', '么', '嘛', '啦', '哎', '唉', '哇', '嗯', 
            '哼', '哪', '什么', '怎么', '为什么', '怎样', '如何', '什么样', '这样', '那样', '这么', 
            '那么', '多少', '几', '谁', '哪里', '哪儿', '什么时候', '何时', '为何', '怎么办', 
            '怎么样', '这些', '那些', '一些', '一点', '一下', '一直', '一定', '一般', '一样', 
            '一会儿', '一边', '一起',
            # 添加更多量词
            '个', '只', '条', '张', '片', '块', '本', '册', '页', '幅', '面', '篇', '份', 
            '朵', '颗', '粒', '座', '幢', '栋', '间', '层', '家', '户', '位', '名', '群',
            '双', '对', '打', '副', '套', '批', '组', '串', '包', '箱', '袋', '瓶', '罐',
            # 添加更多介词
            '按', '按照', '把', '被', '比', '比如', '除', '除了', '当', '对', '对于', 
            '根据', '关于', '跟', '和', '将', '经', '经过', '靠', '连', '论', '通过',
            '同', '往', '为', '为了', '围绕', '于', '由', '由于', '与', '在', '沿', '沿着',
            '依', '依照', '以', '因', '因为', '用', '由', '与', '自', '自从'
        }
        
        # 过滤掉停用词和标点符号,只保留名词和动词
        filtered_words = []
        for word in words:
            if word not in stop_words and not word.strip() in {
                '。', '，', '、', '：', '；', '！', '？', '"', '"', ''', ''', 
                '（', '）', '【', '】', '《', '》', '…', '—', '·', '、', '~', 
                '～', '+', '=', '-'
            }:
                filtered_words.append(word)
        
        # 统计词频
        word_freq = {}
        for word in filtered_words:
            word_freq[word] = word_freq.get(word, 0) + 1
        
        # 按词频排序，取前3个
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        top_words = [word for word, freq in sorted_words[:3]]
        
        return top_words if top_words else None

topic_identifier = TopicIdentifier()