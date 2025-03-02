# -*- coding: utf-8 -*-
import sys
import jieba
import networkx as nx
import matplotlib.pyplot as plt
import math
from collections import Counter
import datetime
import random
import time
import os
# from chat.config import global_config
sys.path.append("C:/GitHub/MaiMBot")  # 添加项目根目录到 Python 路径
from src.common.database import Database  # 使用正确的导入语法
from src.plugins.memory_system.llm_module import LLMModel

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

def get_cloest_chat_from_db(db, length: int, timestamp: str):
    """从数据库中获取最接近指定时间戳的聊天记录"""
    chat_text = ''
    closest_record = db.db.messages.find_one({"time": {"$lte": timestamp}}, sort=[('time', -1)])
    
    if closest_record:
        closest_time = closest_record['time']
        group_id = closest_record['group_id']  # 获取groupid
        # 获取该时间戳之后的length条消息，且groupid相同
        chat_record = list(db.db.messages.find({"time": {"$gt": closest_time}, "group_id": group_id}).sort('time', 1).limit(length))
        for record in chat_record:
            time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(record['time'])))
            chat_text += f'[{time_str}] {record["user_nickname"] or "用户" + str(record["user_id"])}: {record["processed_plain_text"]}\n'
        return chat_text
    
    return ''

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
        
        # print(f"距离time最近的消息时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(closest_record['time'])))}")
        
        if closest_record:
            closest_time = closest_record['time']
            group_id = closest_record['group_id']  # 获取groupid
            # 获取该时间戳之后的length条消息，且groupid相同
            chat_record = list(self.db.db.messages.find({"time": {"$gt": closest_time}, "group_id": group_id}).sort('time', 1).limit(length))
            for record in chat_record:
                if record:
                    time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(record['time'])))
                    chat_text += f'[{time_str}] {record["user_nickname"] or "用户" + str(record["user_id"])}: {record["processed_plain_text"]}\n'  # 添加发送者和时间信息
            return chat_text
        
        return []  # 如果没有找到记录，返回空列表

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
        self.llm_model = LLMModel()
        self.llm_model_small = LLMModel(model_name="deepseek-ai/DeepSeek-V2.5")
        
    def get_memory_sample(self,chat_size=20,time_frequency:dict={'near':2,'mid':4,'far':3}):
        current_timestamp = datetime.datetime.now().timestamp()
        chat_text = []
        #短期：1h   中期：4h   长期：24h
        for _ in range(time_frequency.get('near')):  # 循环10次
            random_time = current_timestamp - random.randint(1, 3600)  # 随机时间
            chat_ = get_cloest_chat_from_db(db=self.memory_graph.db, length=chat_size, timestamp=random_time)
            chat_text.append(chat_)  
        for _ in range(time_frequency.get('mid')):  # 循环10次
            random_time = current_timestamp - random.randint(3600, 3600*4)  # 随机时间
            chat_ = get_cloest_chat_from_db(db=self.memory_graph.db, length=chat_size, timestamp=random_time)
            chat_text.append(chat_)  
        for _ in range(time_frequency.get('far')):  # 循环10次
            random_time = current_timestamp - random.randint(3600*4, 3600*24)  # 随机时间
            chat_ = get_cloest_chat_from_db(db=self.memory_graph.db, length=chat_size, timestamp=random_time)
            chat_text.append(chat_)
        return chat_text
    
    def build_memory(self,chat_size=12):
        #最近消息获取频率
        time_frequency = {'near':1,'mid':2,'far':2}
        memory_sample = self.get_memory_sample(chat_size,time_frequency)
        
                #加载进度可视化
        for i, input_text in enumerate(memory_sample, 1):
            progress = (i / len(memory_sample)) * 100
            bar_length = 30
            filled_length = int(bar_length * i // len(memory_sample))
            bar = '█' * filled_length + '-' * (bar_length - filled_length)
            print(f"\n进度: [{bar}] {progress:.1f}% ({i}/{len(memory_sample)})")
            # print(f"第{i}条消息: {input_text}")
            if input_text:
                # 生成压缩后记忆
                first_memory = set()
                first_memory = self.memory_compress(input_text, 2.5)
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
    
    def memory_compress(self, input_text, rate=1):
        information_content = calculate_information_content(input_text)
        print(f"文本的信息量（熵）: {information_content:.4f} bits")
        topic_num = max(1, min(5, int(information_content * rate / 4)))
        topic_prompt = find_topic(input_text, topic_num)
        topic_response = self.llm_model.generate_response(topic_prompt)
        # 检查 topic_response 是否为元组
        if isinstance(topic_response, tuple):
            topics = topic_response[0].split(",")  # 假设第一个元素是我们需要的字符串
        else:
            topics = topic_response.split(",")
        compressed_memory = set()
        for topic in topics:
            topic_what_prompt = topic_what(input_text,topic)
            topic_what_response = self.llm_model_small.generate_response(topic_what_prompt)
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

def visualize_graph(memory_graph: Memory_graph, color_by_memory: bool = False):
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
    plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号
    
    G = memory_graph.G
    
    # 创建一个新图用于可视化
    H = G.copy()
    
    # 移除只有一条记忆的节点和连接数少于3的节点
    nodes_to_remove = []
    for node in H.nodes():
        memory_items = H.nodes[node].get('memory_items', [])
        memory_count = len(memory_items) if isinstance(memory_items, list) else (1 if memory_items else 0)
        degree = H.degree(node)
        if memory_count <= 1 or degree <= 2:
            nodes_to_remove.append(node)
    
    H.remove_nodes_from(nodes_to_remove)
    
    # 如果过滤后没有节点，则返回
    if len(H.nodes()) == 0:
        print("过滤后没有符合条件的节点可显示")
        return
    
    # 保存图到本地
    nx.write_gml(H, "memory_graph.gml")  # 保存为 GML 格式

    # 根据连接条数或记忆数量设置节点颜色
    node_colors = []
    nodes = list(H.nodes())  # 获取图中实际的节点列表
    
    if color_by_memory:
        # 计算每个节点的记忆数量
        memory_counts = []
        for node in nodes:
            memory_items = H.nodes[node].get('memory_items', [])
            if isinstance(memory_items, list):
                count = len(memory_items)
            else:
                count = 1 if memory_items else 0
            memory_counts.append(count)
        max_memories = max(memory_counts) if memory_counts else 1
        
        for count in memory_counts:
            # 使用不同的颜色方案：红色表示记忆多，蓝色表示记忆少
            if max_memories > 0:
                intensity = min(1.0, count / max_memories)
                color = (intensity, 0, 1.0 - intensity)  # 从蓝色渐变到红色
            else:
                color = (0, 0, 1)  # 如果没有记忆，则为蓝色
            node_colors.append(color)
    else:
        # 使用原来的连接数量着色方案
        max_degree = max(H.degree(), key=lambda x: x[1])[1] if H.degree() else 1
        for node in nodes:
            degree = H.degree(node)
            if max_degree > 0:
                red = min(1.0, degree / max_degree)
                blue = 1.0 - red
                color = (red, 0, blue)
            else:
                color = (0, 0, 1)
            node_colors.append(color)
    
    # 绘制图形
    plt.figure(figsize=(12, 8))
    pos = nx.spring_layout(H, k=1, iterations=50)
    nx.draw(H, pos, 
           with_labels=True, 
           node_color=node_colors,
           node_size=2000,
           font_size=10,
           font_family='SimHei',
           font_weight='bold')
    
    title = '记忆图谱可视化 - ' + ('按记忆数量着色' if color_by_memory else '按连接数量着色')
    plt.title(title, fontsize=16, fontfamily='SimHei')
    plt.show()

def main():
    # 初始化数据库
    Database.initialize(
          host= os.getenv("MONGODB_HOST"),
          port= int(os.getenv("MONGODB_PORT")),
          db_name=  os.getenv("DATABASE_NAME"),
          username= os.getenv("MONGODB_USERNAME"),
          password= os.getenv("MONGODB_PASSWORD"),
          auth_source=os.getenv("MONGODB_AUTH_SOURCE")
    )
    
    start_time = time.time()
    
    # 创建记忆图
    memory_graph = Memory_graph()
    # 加载数据库中存储的记忆图
    memory_graph.load_graph_from_db()
    # 创建海马体
    hippocampus = Hippocampus(memory_graph)
    
    end_time = time.time()
    print(f"\033[32m[加载海马体耗时: {end_time - start_time:.2f} 秒]\033[0m")
    
    # 构建记忆
    hippocampus.build_memory(chat_size=25)
    
    # 展示两种不同的可视化方式
    print("\n按连接数量着色的图谱：")
    visualize_graph(memory_graph, color_by_memory=False)
    
    print("\n按记忆数量着色的图谱：")
    visualize_graph(memory_graph, color_by_memory=True)
    
    # 交互式查询
    while True:
        query = input("请输入新的查询概念（输入'退出'以结束）：")
        if query.lower() == '退出':
            break
        items_list = memory_graph.get_related_item(query)
        if items_list:
            for memory_item in items_list:
                print(memory_item)
        else:
            print("未找到相关记忆。")
            
    while True:
        query = input("请输入问题：")
        
        if query.lower() == '退出':
            break
        
        topic_prompt = find_topic(query, 3)
        topic_response = hippocampus.llm_model.generate_response(topic_prompt)
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

if __name__ == "__main__":
    main()

    
