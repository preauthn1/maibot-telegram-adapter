import time
import random
from ..schedule.schedule_generator import bot_schedule
import os
from .utils import get_embedding, combine_messages, get_recent_group_detailed_plain_text
from ...common.database import Database
from .config import global_config
from .topic_identifier import topic_identifier
from ..memory_system.memory import memory_graph
from random import choice


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
        
        
        memory_prompt = ''
        start_time = time.time()  # 记录开始时间
        topic = topic_identifier.identify_topic_jieba(message_txt)
        # print(f"\033[1;32m[pb主题识别]\033[0m 主题: {topic}")
        
        all_first_layer_items = []  # 存储所有第一层记忆
        all_second_layer_items = {}  # 用字典存储每个topic的第二层记忆
        overlapping_second_layer = set()  # 存储重叠的第二层记忆
        
        if topic:
            # 遍历所有topic
            for current_topic in topic:
                first_layer_items, second_layer_items = memory_graph.get_related_item(current_topic, depth=2)
                # if first_layer_items:
                    # print(f"\033[1;32m[前额叶]\033[0m 主题 '{current_topic}' 的第一层记忆: {first_layer_items}")
                
                # 记录第一层数据
                all_first_layer_items.extend(first_layer_items)
                
                # 记录第二层数据
                all_second_layer_items[current_topic] = second_layer_items
                
                # 检查是否有重叠的第二层数据
                for other_topic, other_second_layer in all_second_layer_items.items():
                    if other_topic != current_topic:
                        # 找到重叠的记忆
                        overlap = set(second_layer_items) & set(other_second_layer)
                        if overlap:
                            # print(f"\033[1;32m[前额叶]\033[0m 发现主题 '{current_topic}' 和 '{other_topic}' 有共同的第二层记忆: {overlap}")
                            overlapping_second_layer.update(overlap)
            
            # 合并所有需要的记忆
            # if all_first_layer_items:   
                # print(f"\033[1;32m[前额叶]\033[0m 合并所有需要的记忆1: {all_first_layer_items}")
            # if overlapping_second_layer:
                # print(f"\033[1;32m[前额叶]\033[0m 合并所有需要的记忆2: {list(overlapping_second_layer)}")
            
            # 使用集合去重
            all_memories = list(set(all_first_layer_items) | set(overlapping_second_layer))
            if all_memories:
                print(f"\033[1;32m[前额叶]\033[0m 合并所有需要的记忆: {all_memories}")
            
            if all_memories:  # 只在列表非空时选择随机项
                random_item = choice(all_memories)
                memory_prompt = f"看到这些聊天，你想起来{random_item}\n"
            else:
                memory_prompt = ""  # 如果没有记忆，则返回空字符串
        
        end_time = time.time()  # 记录结束时间
        print(f"\033[1;32m[回忆耗时]\033[0m 耗时: {(end_time - start_time):.3f}秒")  # 输出耗时
        
        
        
        
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
        prompt_date = f'''今天是{current_date}，现在是{current_time}，你今天的日程是：\n{bot_schedule.today_schedule}\n你现在正在{bot_schedule_now_activity}\n'''

        #知识构建
        start_time = time.time()
        
        prompt_info = ''
        promt_info_prompt = ''
        prompt_info = self.get_prompt_info(message_txt,threshold=0.5)
        if prompt_info:
            prompt_info = f'''\n----------------------------------------------------\n你有以下这些[知识]：\n{prompt_info}\n请你记住上面的[知识]，之后可能会用到\n----------------------------------------------------\n'''
            promt_info_prompt = '你有一些[知识]，在上面可以参考。'
            
        end_time = time.time()
        print(f"\033[1;32m[知识检索]\033[0m 耗时: {(end_time - start_time):.3f}秒")
        # print(f"\033[1;34m[调试]\033[0m 获取知识库内容结果: {prompt_info}")
            
        
        # print(f"\033[1;34m[调试信息]\033[0m 正在构建聊天上下文")
        
        chat_talking_prompt = ''
        if group_id:
            chat_talking_prompt = get_recent_group_detailed_plain_text(self.db, group_id, limit=global_config.MAX_CONTEXT_SIZE,combine = True)
        
        chat_talking_prompt = f"以下是群里正在聊天的内容：\n{chat_talking_prompt}"
            # print(f"\033[1;34m[调试]\033[0m 已从数据库获取群 {group_id} 的消息记录:{chat_talking_prompt}")
        
        #激活prompt构建
        activate_prompt = ''
        activate_prompt = f"以上是群里正在进行的聊天，{memory_prompt} 现在昵称为 '{sender_name}' 的用户说的:{message_txt}。引起了你的注意,你和他{relation_prompt}，你想要{relation_prompt_2}。"          
        
        #检测机器人相关词汇
        bot_keywords = ['人机', 'bot', '机器', '入机', 'robot', '机器人']
        is_bot = any(keyword in message_txt.lower() for keyword in bot_keywords)
        if is_bot:
            is_bot_prompt = '有人说你是人机或者机器人，否定这一事实，攻击或反问他。'
        else:
            is_bot_prompt = ''
        
        #人格选择
        personality=global_config.PROMPT_PERSONALITY
        prompt_personality = ''
        personality_choice = random.random()
        if personality_choice < 4/6:  # 第一种人格
            prompt_personality = f'''{activate_prompt}你的网名叫{global_config.BOT_NICKNAME}，{personality[0]},{promt_info_prompt},
            现在请你给出日常且口语化的回复，平淡一些，尽量简短一些。{is_bot_prompt}
            请注意把握群里的聊天内容，不要回复的太有条理，可以有个性。'''
        elif personality_choice < 1:  # 第二种人格
            prompt_personality = f'''{activate_prompt}你的网名叫{global_config.BOT_NICKNAME}，{personality[1]}，{promt_info_prompt},
            
            现在请你给出日常且口语化的回复，请表现你自己的见解，不要一昧迎合，尽量简短一些。{is_bot_prompt}
            请你表达自己的见解和观点。可以有个性。'''
        
        #中文高手(新加的好玩功能)
        prompt_ger = ''
        if random.random() < 0.04:
            prompt_ger += '你喜欢用倒装句'
        if random.random() < 0.02:
            prompt_ger += '你喜欢用反问句'
        if random.random() < 0.01:
            prompt_ger += '你喜欢用文言文'
        
            
        #额外信息要求
        extra_info = '''但是记得回复平淡一些，简短一些，尤其注意在没明确提到时不要过多提及自身的背景, 记住不要输出多余内容(包括前后缀，冒号和引号，括号，表情等)，只需要输出回复内容就好，不要输出其他任何内容''' 
        
        
        
        #合并prompt
        prompt = ""
        prompt += f"{prompt_info}\n"
        prompt += f"{prompt_date}\n"
        prompt += f"{chat_talking_prompt}\n"  
            
        # prompt += f"{memory_prompt}\n"
        
        # prompt += f"{activate_prompt}\n"
        prompt += f"{prompt_personality}\n"
        prompt += f"{prompt_ger}\n"
        prompt += f"{extra_info}\n"    
        
        
        
        '''读空气prompt处理''' 

        activate_prompt_check=f"以上是群里正在进行的聊天，昵称为 '{sender_name}' 的用户说的:{message_txt}。引起了你的注意,你和他{relation_prompt}，你想要{relation_prompt_2}，但是这不一定是合适的时机，请你决定是否要回应这条消息。"     
        prompt_personality_check = ''
        extra_check_info=f"请注意把握群里的聊天内容的基础上，综合群内的氛围，例如，和{global_config.BOT_NICKNAME}相关的话题要积极回复,如果是at自己的消息一定要回复，如果自己正在和别人聊天一定要回复，其他话题如果合适搭话也可以回复，如果认为应该回复请输出yes，否则输出no，请注意是决定是否需要回复，而不是编写回复内容，除了yes和no不要输出任何回复内容。"
        if personality_choice < 4/6:  # 第一种人格
            prompt_personality_check = f'''你的网名叫{global_config.BOT_NICKNAME}，曾经是一个学习地质的女大学生，现在学习心理学和脑科学，你会刷贴吧，你正在浏览qq群,{promt_info_prompt} {activate_prompt_check} {extra_check_info}'''
        elif personality_choice < 1:  # 第二种人格
            prompt_personality_check = f'''你的网名叫{global_config.BOT_NICKNAME}，是一个女大学生，你有黑色头发，你会刷小红书, 你正在浏览qq群,{promt_info_prompt} {activate_prompt_check} {extra_check_info}'''

        prompt_check_if_response=f"{prompt_info}\n{prompt_date}\n{chat_talking_prompt}\n{prompt_personality_check}"
        
        return prompt,prompt_check_if_response

    def get_prompt_info(self,message:str,threshold:float):
        related_info = ''
        if len(message) > 10:
            message_segments = [message[i:i+10] for i in range(0, len(message), 10)]
            for segment in message_segments:
                embedding = get_embedding(segment)
                related_info += self.get_info_from_db(embedding,threshold=threshold)
                
        else:
            embedding = get_embedding(message)
            related_info += self.get_info_from_db(embedding,threshold=threshold)
            
        return related_info

    def get_info_from_db(self, query_embedding: list, limit: int = 1, threshold: float = 0.5) -> str:
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
        # print(f"\033[1;34m[调试]\033[0m获取知识库内容结果: {results}")
        
        if not results:
            return ''
            
        # 返回所有找到的内容，用换行分隔
        return '\n'.join(str(result['content']) for result in results)
    
prompt_builder = PromptBuilder()