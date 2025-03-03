# -*- coding: utf-8 -*-
import os
import jieba
import networkx as nx
import matplotlib.pyplot as plt
from collections import Counter
import datetime
import random
import time
from ..chat.config import global_config
from ...common.database import Database # 使用正确的导入语法
from ..chat.utils import calculate_information_content, get_cloest_chat_from_db
from ..models.utils_model import LLM_request
class Memory_graph:
    def __init__(self):
        self.G = nx.Graph()  # 使用 networkx 的图结构
        self.db = Database.get_instance()
        
    def connect_dot(self, concept1, concept2):
        self.G.add_edge(concept1, concept2)
    
    def add_dot(self, concept, memory):
        if concept in self.G:
            # 如果节点已存在，将新记忆添加到现有列表中
            if 'memory_items' in self.G.nodes[concept]:
                if not isinstance(self.G.nodes[concept]['memory_items'], list):
                    # 如果当前不是列表，将其转换为列表
                    self.G.nodes[concept]['memory_items'] = [self.G.nodes[concept]['memory_items']]
                self.G.nodes[concept]['memory_items'].append(memory)
            else:
                self.G.nodes[concept]['memory_items'] = [memory]
        else:
            # 如果是新节点，创建新的记忆列表
            self.G.add_node(concept, memory_items=[memory])
        
    def get_dot(self, concept):
        # 检查节点是否存在于图中
        if concept in self.G:
            # 从图中获取节点数据
            node_data = self.G.nodes[concept]
            # print(node_data)
            # 创建新的Memory_dot对象
            return concept,node_data
        return None

    def get_related_item(self, topic, depth=1):
        if topic not in self.G:
            return [], []
            
        first_layer_items = []
        second_layer_items = []
        
        # 获取相邻节点
        neighbors = list(self.G.neighbors(topic))
        # print(f"第一层: {topic}")
        
        # 获取当前节点的记忆项
        node_data = self.get_dot(topic)
        if node_data:
            concept, data = node_data
            if 'memory_items' in data:
                memory_items = data['memory_items']
                if isinstance(memory_items, list):
                    first_layer_items.extend(memory_items)
                else:
                    first_layer_items.append(memory_items)
        
        # 只在depth=2时获取第二层记忆
        if depth >= 2:
            # 获取相邻节点的记忆项
            for neighbor in neighbors:
                # print(f"第二层: {neighbor}")
                node_data = self.get_dot(neighbor)
                if node_data:
                    concept, data = node_data
                    if 'memory_items' in data:
                        memory_items = data['memory_items']
                        if isinstance(memory_items, list):
                            second_layer_items.extend(memory_items)
                        else:
                            second_layer_items.append(memory_items)
        
        return first_layer_items, second_layer_items
    
    @property
    def dots(self):
        # 返回所有节点对应的 Memory_dot 对象
        return [self.get_dot(node) for node in self.G.nodes()]

    def save_graph_to_db(self):
        # 保存节点
        for node in self.G.nodes(data=True):
            concept = node[0]
            memory_items = node[1].get('memory_items', [])
            
            # 查找是否存在同名节点
            existing_node = self.db.db.graph_data.nodes.find_one({'concept': concept})
            if existing_node:
                # 如果存在,合并memory_items并去重
                existing_items = existing_node.get('memory_items', [])
                if not isinstance(existing_items, list):
                    existing_items = [existing_items] if existing_items else []
                
                # 合并并去重
                all_items = list(set(existing_items + memory_items))
                
                # 更新节点
                self.db.db.graph_data.nodes.update_one(
                    {'concept': concept},
                    {'$set': {'memory_items': all_items}}
                )
            else:
                # 如果不存在,创建新节点
                node_data = {
                    'concept': concept,
                    'memory_items': memory_items
                }
                self.db.db.graph_data.nodes.insert_one(node_data)
        
        # 保存边
        for edge in self.G.edges():
            source, target = edge
            
            # 查找是否存在同样的边
            existing_edge = self.db.db.graph_data.edges.find_one({
                'source': source,
                'target': target
            })
            
            if existing_edge:
                # 如果存在,增加num属性
                num = existing_edge.get('num', 1) + 1
                self.db.db.graph_data.edges.update_one(
                    {'source': source, 'target': target},
                    {'$set': {'num': num}}
                )
            else:
                # 如果不存在,创建新边
                edge_data = {
                    'source': source,
                    'target': target,
                    'num': 1
                }
                self.db.db.graph_data.edges.insert_one(edge_data)

    def load_graph_from_db(self):
        # 清空当前图
        self.G.clear()
        # 加载节点
        nodes = self.db.db.graph_data.nodes.find()
        for node in nodes:
            memory_items = node.get('memory_items', [])
            if not isinstance(memory_items, list):
                memory_items = [memory_items] if memory_items else []
            self.G.add_node(node['concept'], memory_items=memory_items)
        # 加载边
        edges = self.db.db.graph_data.edges.find()
        for edge in edges:
            self.G.add_edge(edge['source'], edge['target'], num=edge.get('num', 1))





# 海马体 
class Hippocampus:
    def __init__(self,memory_graph:Memory_graph):
        self.memory_graph = memory_graph
        self.llm_model = LLM_request(model = global_config.llm_normal,temperature=0.5)
        self.llm_model_small = LLM_request(model = global_config.llm_normal_minor,temperature=0.5)
        
    def get_memory_sample(self,chat_size=20,time_frequency:dict={'near':2,'mid':4,'far':3}):
        current_timestamp = datetime.datetime.now().timestamp()
        chat_text = []
        #短期：1h   中期：4h   长期：24h
        for _ in range(time_frequency.get('near')):  # 循环10次
            random_time = current_timestamp - random.randint(1, 3600)  # 随机时间
            # print(f"获得 最近 随机时间戳对应的时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(random_time))}")
            chat_ = get_cloest_chat_from_db(db=self.memory_graph.db, length=chat_size, timestamp=random_time)
            chat_text.append(chat_)  
        for _ in range(time_frequency.get('mid')):  # 循环10次
            random_time = current_timestamp - random.randint(3600, 3600*4)  # 随机时间
            # print(f"获得 最近 随机时间戳对应的时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(random_time))}")
            chat_ = get_cloest_chat_from_db(db=self.memory_graph.db, length=chat_size, timestamp=random_time)
            chat_text.append(chat_)  
        for _ in range(time_frequency.get('far')):  # 循环10次
            random_time = current_timestamp - random.randint(3600*4, 3600*24)  # 随机时间
            # print(f"获得 最近 随机时间戳对应的时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(random_time))}")
            chat_ = get_cloest_chat_from_db(db=self.memory_graph.db, length=chat_size, timestamp=random_time)
            chat_text.append(chat_)
        return chat_text
    
    async def memory_compress(self, input_text, rate=1):
        information_content = calculate_information_content(input_text)
        print(f"文本的信息量（熵）: {information_content:.4f} bits")
        topic_num = max(1, min(5, int(information_content * rate / 4)))
        topic_prompt = find_topic(input_text, topic_num)
        topic_response = await self.llm_model.generate_response(topic_prompt)
        # 检查 topic_response 是否为元组
        if isinstance(topic_response, tuple):
            topics = topic_response[0].split(",")  # 假设第一个元素是我们需要的字符串
        else:
            topics = topic_response.split(",")
        compressed_memory = set()
        for topic in topics:
            topic_what_prompt = topic_what(input_text,topic)
            topic_what_response = await self.llm_model_small.generate_response(topic_what_prompt)
            compressed_memory.add((topic.strip(), topic_what_response[0]))  # 将话题和记忆作为元组存储
        return compressed_memory
    
    async def build_memory(self,chat_size=12):
        #最近消息获取频率
        time_frequency = {'near':1,'mid':2,'far':2}
        memory_sample = self.get_memory_sample(chat_size,time_frequency)
        # print(f"\033[1;32m[记忆构建]\033[0m 获取记忆样本: {memory_sample}")   
        for i, input_text in enumerate(memory_sample, 1):
            #加载进度可视化
            progress = (i / len(memory_sample)) * 100
            bar_length = 30
            filled_length = int(bar_length * i // len(memory_sample))
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            print(f"\n进度: [{bar}] {progress:.1f}% ({i}/{len(memory_sample)})")
            if input_text:
                # 生成压缩后记忆
                first_memory = set()
                first_memory = await self.memory_compress(input_text, 2.5)
                #将记忆加入到图谱中
                for topic, memory in first_memory:
                    topics = segment_text(topic)
                    print(f"\033[1;34m话题\033[0m: {topic},节点: {topics}, 记忆: {memory}")
                    for split_topic in topics:
                        self.memory_graph.add_dot(split_topic,memory)
                    for split_topic in topics:
                        for other_split_topic in topics:
                            if split_topic != other_split_topic:
                                self.memory_graph.connect_dot(split_topic, other_split_topic)
            else:
                print(f"空消息 跳过")
        self.memory_graph.save_graph_to_db()


def segment_text(text):
    seg_text = list(jieba.cut(text))
    return seg_text    

def find_topic(text, topic_num):
    prompt = f'这是一段文字：{text}。请你从这段话中总结出{topic_num}个话题，帮我列出来，用逗号隔开，尽可能精简。只需要列举{topic_num}个话题就好，不要告诉我其他内容。'
    return prompt

def topic_what(text, topic):
    prompt = f'这是一段文字：{text}。我想知道这记忆里有什么关于{topic}的话题，帮我总结成一句自然的话，可以包含时间和人物。只输出这句话就好'
    return prompt


from nonebot import get_driver
driver = get_driver()
config = driver.config

start_time = time.time()

Database.initialize(
    host= config.mongodb_host,
    port= int(config.mongodb_port),
    db_name=  config.database_name,
    username= config.mongodb_username,
    password= config.mongodb_password,
    auth_source=config.mongodb_auth_source
)
#创建记忆图
memory_graph = Memory_graph()
#加载数据库中存储的记忆图
memory_graph.load_graph_from_db()
#创建海马体
hippocampus = Hippocampus(memory_graph)

end_time = time.time()
print(f"\033[32m[加载海马体耗时: {end_time - start_time:.2f} 秒]\033[0m")