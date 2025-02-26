import time
import random
from dotenv import load_dotenv
from ..schedule.schedule_generator import bot_schedule
import os
from .utils import get_embedding, combine_messages, get_recent_group_messages
from ...common.database import Database

# 获取当前文件的绝对路径
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..'))
load_dotenv(os.path.join(root_dir, '.env'))


class PromptBuilder:
    def __init__(self):
        self.prompt_built = ''
        self.activate_messages = ''
        self.db = Database.get_instance()

    def _build_prompt(self, 
                    message_txt: str, 
                    sender_name: str = "某人",
                    relationship_value: float = 0.0,
                    group_id: int = None) -> str:
        """构建prompt
        
        Args:
            message_txt: 消息文本
            sender_name: 发送者昵称
            relationship_value: 关系值
            group_id: 群组ID
            
        Returns:
            str: 构建好的prompt
        """
        #先禁用关系
        if 0 > 30:
            relation_prompt = "关系特别特别好，你很喜欢喜欢他"
            relation_prompt_2 = "热情发言或者回复"
        elif 0 <-20:
            relation_prompt = "关系很差，你很讨厌他"
            relation_prompt_2 = "骂他"
        else:
            relation_prompt = "关系一般"
            relation_prompt_2 = "发言或者回复"
        
        #开始构建prompt
        
        #日程构建
        current_date = time.strftime("%Y-%m-%d", time.localtime())
        current_time = time.strftime("%H:%M:%S", time.localtime())
        bot_schedule_now_time,bot_schedule_now_activity = bot_schedule.get_current_task()
        prompt_date = f'''今天是{current_date}，现在是{current_time}，你今天的日程是：\n{bot_schedule.today_schedule}\n'''

        #知识构建
        prompt_info = ''
        promt_info_prompt = ''
        prompt_info = self.get_prompt_info(message_txt)
        if prompt_info:
            prompt_info = f'''\n----------------------------------------------------\n你有以下这些[知识]：
            \n{prompt_info}\n
            请你记住上面的[知识]，之后可能会用到\n----------------------------------------------------\n'''
            promt_info_prompt = '你有一些[知识]，在上面可以参考。'
        
        
        chat_talking_prompt = ''
        if group_id:
            # 从数据库获取最近消息
            message_objects = get_recent_group_messages(self.db, group_id, limit=16)
            if message_objects:
                chat_talking_prompt = combine_messages(message_objects)
                # print(f"\033[1;34m[调试]\033[0m 已从数据库获取群 {group_id} 的最近{len(message_objects)}条消息记录")
        
        #激活prompt构建
        activate_prompt = ''
        activate_prompt = f"以上是群里正在进行的聊天，昵称为 '{sender_name}' 的用户说的:{message_txt}。引起了你的注意,你和他{relation_prompt}，你想要{relation_prompt_2} \n"          
        
        # 检测机器人相关词汇
        bot_keywords = ['人机', 'bot', '机器', '入机', 'robot', '机器人']
        is_bot = any(keyword in message_txt.lower() for keyword in bot_keywords)
        if is_bot:
            is_bot_prompt = '有人说你是人机或者机器人，否定这一事实，攻击或反问他。'
        else:
            is_bot_prompt = ''
        
        #人格选择
        prompt_personality = ''
        personality_choice = random.random()
        if personality_choice < 4/6:  # 第一种人格
            prompt_personality = f'''你的网名叫麦麦，是一个学习地质的女大学生，喜欢摄影，你会刷贴吧，你现在正在{bot_schedule_now_activity},并且正在浏览qq群,{promt_info_prompt}
            现在请你给出日常且口语化的回复，平淡一些，尽量简短一些,不要输出感叹号。{is_bot_prompt}
            不要回复的太有逻辑或者太有条理，可以有个性。'''
        elif personality_choice < 1:  # 第二种人格
            prompt_personality = f'''你的网名叫麦麦，是一个女大学生，你有黑色头发，你会刷小红书，你现在正在{bot_schedule_now_activity},并且正在浏览qq群,{promt_info_prompt}
            现在请你给出日常且口语化的回复，请表现你自己的见解，不要一昧迎合，尽量简短一些,不要输出感叹号。{is_bot_prompt}
            请你表达自己的见解和观点。可以有个性。'''
            
        #额外信息要求
        extra_info = '''但是记得回复平淡一些，简短一些，不要过多提及自身的背景, 记住不要输出多余内容(包括前后缀，冒号和引号，括号，表情等),只需要输出回复内容就好，不要输出其他任何内容''' 
        
        #合并prompt
        prompt = ""
        # prompt += f"{prompt_info}\n"
        prompt += f"{prompt_date}\n"
        prompt += f"{chat_talking_prompt}\n"       
        prompt += f"{activate_prompt}\n"
        prompt += f"{prompt_personality}\n"
        prompt += f"{extra_info}\n"     
        
        return prompt

    def get_prompt_info(self,message:str):
        related_info = ''
        if len(message) > 10:
            message_segments = [message[i:i+10] for i in range(0, len(message), 10)]
            for segment in message_segments:
                embedding = get_embedding(segment)
                related_info += self.get_info_from_db(embedding)
                
        else:
            embedding = get_embedding(message)
            related_info += self.get_info_from_db(embedding)
            
    def get_info_from_db(self, query_embedding: list, limit: int = 1, threshold: float = 0.5) -> str:
        """
        从知识库中查找与输入向量最相似的内容
        Args:
            query_embedding: 查询向量
            limit: 返回结果数量，默认为2
            threshold: 相似度阈值，默认为0.5
        Returns:
            str: 找到的相关信息，如果相似度低于阈值则返回空字符串
        """
        if not query_embedding:
            return ''
            
        # 使用余弦相似度计算
        pipeline = [
            {
                "$addFields": {
                    "dotProduct": {
                        "$reduce": {
                            "input": {"$range": [0, {"$size": "$embedding"}]},
                            "initialValue": 0,
                            "in": {
                                "$add": [
                                    "$$value",
                                    {"$multiply": [
                                        {"$arrayElemAt": ["$embedding", "$$this"]},
                                        {"$arrayElemAt": [query_embedding, "$$this"]}
                                    ]}
                                ]
                            }
                        }
                    },
                    "magnitude1": {
                        "$sqrt": {
                            "$reduce": {
                                "input": "$embedding",
                                "initialValue": 0,
                                "in": {"$add": ["$$value", {"$multiply": ["$$this", "$$this"]}]}
                            }
                        }
                    },
                    "magnitude2": {
                        "$sqrt": {
                            "$reduce": {
                                "input": query_embedding,
                                "initialValue": 0,
                                "in": {"$add": ["$$value", {"$multiply": ["$$this", "$$this"]}]}
                            }
                        }
                    }
                }
            },
            {
                "$addFields": {
                    "similarity": {
                        "$divide": ["$dotProduct", {"$multiply": ["$magnitude1", "$magnitude2"]}]
                    }
                }
            },
            {
                "$match": {
                    "similarity": {"$gte": threshold}  # 只保留相似度大于等于阈值的结果
                }
            },
            {"$sort": {"similarity": -1}},
            {"$limit": limit},
            {"$project": {"content": 1, "similarity": 1}}
        ]
        
        results = list(self.db.db.knowledges.aggregate(pipeline))
        
        if not results:
            return ''
            
        # 返回所有找到的内容，用换行分隔
        return '\n'.join(str(result['content']) for result in results)
    
prompt_builder = PromptBuilder()