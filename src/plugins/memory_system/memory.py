# -*- coding: utf-8 -*-
import sys
import jieba
from llm_module import LLMModel
import networkx as nx
import matplotlib.pyplot as plt
import math
from collections import Counter
import datetime
import random
import time

import sys
sys.path.append("C:/GitHub/MegMeg-bot")  # 添加项目根目录到 Python 路径
from src.common.database import Database  # 使用正确的导入语法
   
class Memory_graph:
    def __init__(self):
        self.G = nx.Graph()  # 使用 networkx 的图结构
        self.db = Database.get_instance()
        
    def connect_dot(self, concept1, concept2):
        self.G.add_edge(concept1, concept2)
    
    def add_dot(self, concept, memory):
        self.G.add_node(concept, memory_items=memory)
        
    def get_dot(self, concept):
        # 检查节点是否存在于图中
        if concept in self.G:
            # 从图中获取节点数据
            node_data = self.G.nodes[concept]
            print(node_data)
            # 创建新的Memory_dot对象
            return concept,node_data
        return None

    def get_related_item(self, topic, depth=1):
        if topic not in self.G:
            return set()
            
        items_set = set()
        # 获取相邻节点
        neighbors = list(self.G.neighbors(topic))
        print(f"第一层: {topic}")
        
        # 获取当前节点的记忆项
        node_data = self.get_dot(topic)
        if node_data:
            concept, data = node_data
            if 'memory_items' in data:
                items_set.add(data['memory_items'])
        
        # 获取相邻节点的记忆项
        for neighbor in neighbors:
            print(f"第二层: {neighbor}")
            node_data = self.get_dot(neighbor)
            if node_data:
                concept, data = node_data
                if 'memory_items' in data:
                    items_set.add(data['memory_items'])
        
        return items_set
    
    def store_memory(self):
        for node in self.G.nodes():
            dot_data = {
                "concept": node
            }
            self.db.db.store_memory_dots.insert_one(dot_data)
    
    @property
    def dots(self):
        # 返回所有节点对应的 Memory_dot 对象
        return [self.get_dot(node) for node in self.G.nodes()]
    
    
    def get_random_chat_from_db(self, length: int, timestamp: str):
        # 从数据库中根据时间戳获取离其最近的聊天记录
        chat_text = ''
        closest_record = self.db.db.messages.find_one({"time": {"$lte": timestamp}}, sort=[('time', -1)])  # 调试输出
        print(f"距离time最近的消息时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(closest_record['time'])))}")
        
        if closest_record:
            closest_time = closest_record['time']
            group_id = closest_record['group_id']  # 获取groupid
            # 获取该时间戳之后的length条消息，且groupid相同
            chat_record = list(self.db.db.messages.find({"time": {"$gt": closest_time}, "group_id": group_id}).sort('time', 1).limit(length))
            for record in chat_record:
                time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(record['time'])))
                chat_text += f'[{time_str}] {record["user_nickname"] or "用户" + str(record["user_id"])}: {record["processed_plain_text"]}\n'  # 添加发送者和时间信息
            return chat_text
        
        # all_record = list(self.db.db.messages.aggregate([
        #     {"$match": {"time": {"$exists": True}}},  # 只选择有时间戳的记录
        #     {"$group": {"_id": "$group_id", "records": {"$push": "$$ROOT"}}},
        #     {"$unwind": "$records"},
        #     {"$sort": {"records.time": 1}}
        # ]))
        # for record in all_record:
        #     if 'time' in record:
        #         time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(record['time'])));
        #     else:
        #         print(f"记录中缺少'time'键: {record}")
        #         continue  # 跳过没有时间的记录
        #     chat_text.append(f'[{time_str}] {record["user_nickname"] or "用户" + str(record["user_id"])}: {record["processed_plain_text"]}')  # 添加发送者和时间信息
        # return chat_text
        
        
        return []  # 如果没有找到记录，返回空列表

    def save_graph_to_db(self):
        # 清空现有的图数据
        self.db.db.graph_data.delete_many({})
        # 保存节点
        for node in self.G.nodes(data=True):
            node_data = {
                'concept': node[0],
                'memory_items': node[1].get('memory_items', None)
            }
            self.db.db.graph_data.nodes.insert_one(node_data)
        # 保存边
        for edge in self.G.edges():
            edge_data = {
                'source': edge[0],
                'target': edge[1]
            }
            self.db.db.graph_data.edges.insert_one(edge_data)

    def load_graph_from_db(self):
        # 清空当前图
        self.G.clear()
        # 加载节点
        nodes = self.db.db.graph_data.nodes.find()
        for node in nodes:
            self.G.add_node(node['concept'], memory_items=node['memory_items'])
        # 加载边
        edges = self.db.db.graph_data.edges.find()
        for edge in edges:
            self.G.add_edge(edge['source'], edge['target'])

def calculate_information_content(text):
    
    """计算文本的信息量（熵）"""
    # 统计字符频率
    char_count = Counter(text)
    total_chars = len(text)
    
    # 计算熵
    entropy = 0
    for count in char_count.values():
        probability = count / total_chars
        entropy -= probability * math.log2(probability)
    
    return entropy

def main():
    # 初始化数据库
    Database.initialize(
        "127.0.0.1",
        27017,
        "MegBot"
    )
    
    memory_graph = Memory_graph()
    # 创建LLM模型实例
    llm_model = LLMModel()
    llm_model_small = LLMModel(model_name="deepseek-ai/DeepSeek-V2.5")
    
    # 使用当前时间戳进行测试
    current_timestamp = datetime.datetime.now().timestamp()
    chat_text = []
    
    chat_size =30
    
    for _ in range(60):  # 循环10次
        random_time = current_timestamp - random.randint(1, 3600*3)  # 随机时间
        print(f"随机时间戳对应的时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(random_time))}")
        chat_ = memory_graph.get_random_chat_from_db(chat_size, random_time)
        chat_text.append(chat_)  # 拼接所有text


    
    for input_text in chat_text:
        print(input_text)
        first_memory = set()
        first_memory = memory_compress(input_text, llm_model_small, llm_model_small, rate=2.5)
        
        #将记忆加入到图谱中
        for topic, memory in first_memory:
            topics = segment_text(topic)
            print(f"话题: {topic},节点: {topics}, 记忆: {memory}")
            for split_topic in topics:
                memory_graph.add_dot(split_topic,memory)
            for split_topic in topics:
                for other_split_topic in topics:
                    if split_topic != other_split_topic:
                        memory_graph.connect_dot(split_topic, other_split_topic)
    
    # memory_graph.store_memory()
    visualize_graph(memory_graph)
    
    memory_graph.save_graph_to_db()
    # memory_graph.load_graph_from_db()
    
    while True:
        query = input("请输入新的查询概念（输入'退出'以结束）：")
        if query.lower() == '退出':
            break
        items_list = memory_graph.get_related_item(query)
        if items_list:
            # print(items_list)
            for memory_item in items_list:
                print(memory_item)
        else:
            print("未找到相关记忆。")
            
    while True:
        query = input("请输入问题：")
        
        if query.lower() == '退出':
            break
        
        topic_prompt = find_topic(query, 3)
        topic_response = llm_model.generate_response(topic_prompt)
        # 检查 topic_response 是否为元组
        if isinstance(topic_response, tuple):
            topics = topic_response[0].split(",")  # 假设第一个元素是我们需要的字符串
        else:
            topics = topic_response.split(",")
        print(topics)
        
        for keyword in topics:
            items_list = memory_graph.get_related_item(keyword)
            if items_list:
                print(items_list)
    
def memory_compress(input_text, llm_model, llm_model_small, rate=1):
    information_content = calculate_information_content(input_text)
    print(f"文本的信息量（熵）: {information_content:.4f} bits")
    topic_num = max(1, min(5, int(information_content * rate / 4)))
    print(topic_num)
    topic_prompt = find_topic(input_text, topic_num)
    topic_response = llm_model.generate_response(topic_prompt)
    # 检查 topic_response 是否为元组
    if isinstance(topic_response, tuple):
        topics = topic_response[0].split(",")  # 假设第一个元素是我们需要的字符串
    else:
        topics = topic_response.split(",")
    print(topics)
    compressed_memory = set()
    for topic in topics:
        topic_what_prompt = topic_what(input_text,topic)
        topic_what_response = llm_model_small.generate_response(topic_what_prompt)
        compressed_memory.add((topic.strip(), topic_what_response[0]))  # 将话题和记忆作为元组存储
    return compressed_memory


def segment_text(text):
    seg_text = list(jieba.cut(text))
    return seg_text    

def find_topic(text, topic_num):
    prompt = f'这是一段文字：{text}。请你从这段话中总结出{topic_num}个话题，帮我列出来，用逗号隔开，尽可能精简。只需要列举{topic_num}个话题就好，不要告诉我其他内容。'
    return prompt

def topic_what(text, topic):
    prompt = f'这是一段文字：{text}。我想知道这记忆里有什么关于{topic}的话题，帮我总结成一句自然的话，可以包含时间和人物。只输出这句话就好'
    return prompt

def visualize_graph(memory_graph: Memory_graph):
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
    plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
    
    G = memory_graph.G
    
    
    # 保存图到本地
    nx.write_gml(G, "memory_graph.gml")  # 保存为 GML 格式

    # 根据连接条数设置节点颜色
    node_colors = []
    nodes = list(G.nodes())  # 获取图中实际的节点列表
    max_degree = max(G.degree(), key=lambda x: x[1])[1] if G.degree() else 1  # 获取最大连接数
    
    for node in nodes:
        degree = G.degree(node)  # 获取节点的度
        # 计算颜色，使用渐变效果
        if max_degree > 0:
            red = min(1.0, degree / max_degree)  # 红色分量随连接数增加而增加
            blue = 1.0 - red  # 蓝色分量随连接数增加而减少
            color = (red, 0, blue)
        else:
            color = (0, 0, 1)  # 如果没有连接，则为蓝色
        node_colors.append(color)
    
    # 绘制图形
    plt.figure(figsize=(12, 8))
    pos = nx.spring_layout(G, k=1, iterations=50)  # 使用弹簧布局，调整参数使布局更合理
    nx.draw(G, pos, 
           with_labels=True, 
           node_color=node_colors,
           node_size=2000,
           font_size=10,
           font_family='SimHei',  # 设置节点标签的字体
           font_weight='bold')
    
    plt.title('记忆图谱可视化', fontsize=16, fontfamily='SimHei')
    plt.show()

if __name__ == "__main__":
    main()

    
