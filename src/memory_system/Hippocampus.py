# -*- coding: utf-8 -*-
import datetime
import math
import random
import time
import re
import jieba
import networkx as nx
import numpy as np
from typing import List, Tuple, Set
from collections import Counter
import traceback

from rich.traceback import install

from src.llm_models.utils_model import LLMRequest
from src.config.config import model_config
from src.common.database.database_model import GraphNodes, GraphEdges  # Peewee Models导入
from src.common.logger import get_logger
from src.chat.utils.utils import cut_key_words


# 添加cosine_similarity函数
def cosine_similarity(v1, v2):
    """计算余弦相似度"""
    dot_product = np.dot(v1, v2)
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    return 0 if norm1 == 0 or norm2 == 0 else dot_product / (norm1 * norm2)


install(extra_lines=3)


def calculate_information_content(text):
    """计算文本的信息量（熵）"""
    char_count = Counter(text)
    total_chars = len(text)
    if total_chars == 0:
        return 0
    entropy = 0
    for count in char_count.values():
        probability = count / total_chars
        entropy -= probability * math.log2(probability)

    return entropy


logger = get_logger("memory")


class MemoryGraph:
    def __init__(self):
        self.G = nx.Graph()  # 使用 networkx 的图结构

    def connect_dot(self, concept1, concept2):
        # 避免自连接
        if concept1 == concept2:
            return

        current_time = datetime.datetime.now().timestamp()

        # 如果边已存在,增加 strength
        if self.G.has_edge(concept1, concept2):
            self.G[concept1][concept2]["strength"] = self.G[concept1][concept2].get("strength", 1) + 1
            # 更新最后修改时间
            self.G[concept1][concept2]["last_modified"] = current_time
        else:
            # 如果是新边,初始化 strength 为 1
            self.G.add_edge(
                concept1,
                concept2,
                strength=1,
                created_time=current_time,  # 添加创建时间
                last_modified=current_time,
            )  # 添加最后修改时间

    async def add_dot(self, concept, memory, hippocampus_instance=None):
        current_time = datetime.datetime.now().timestamp()

        if concept in self.G:
            if "memory_items" in self.G.nodes[concept]:
                # 获取现有的记忆项（已经是str格式）
                existing_memory = self.G.nodes[concept]["memory_items"]
                # 简单连接新旧记忆
                new_memory_str = f"{existing_memory} | {memory}"
                self.G.nodes[concept]["memory_items"] = new_memory_str
                logger.info(f"节点 {concept} 记忆内容已简单拼接并更新：{new_memory_str}")
            else:
                self.G.nodes[concept]["memory_items"] = str(memory)
                # 如果节点存在但没有memory_items,说明是第一次添加memory,设置created_time
                if "created_time" not in self.G.nodes[concept]:
                    self.G.nodes[concept]["created_time"] = current_time
                logger.info(f"节点 {concept} 创建新记忆：{str(memory)}")
            # 更新最后修改时间
            self.G.nodes[concept]["last_modified"] = current_time
        else:
            # 如果是新节点,创建新的记忆字符串
            self.G.add_node(
                concept,
                memory_items=str(memory),
                weight=1.0,  # 新节点初始权重为1.0
                created_time=current_time,  # 添加创建时间
                last_modified=current_time,
            )  # 添加最后修改时间
            logger.info(f"新节点 {concept} 已添加，记忆内容已写入：{str(memory)}")

    def get_dot(self, concept):
        # 检查节点是否存在于图中
        return (concept, self.G.nodes[concept]) if concept in self.G else None

    def get_related_item(self, topic, depth=1):
        if topic not in self.G:
            return [], []

        first_layer_items = []
        second_layer_items = []

        # 获取相邻节点
        neighbors = list(self.G.neighbors(topic))

        # 获取当前节点的记忆项
        node_data = self.get_dot(topic)
        if node_data:
            _, data = node_data
            if "memory_items" in data:
                # 直接使用完整的记忆内容
                if memory_items := data["memory_items"]:
                    first_layer_items.append(memory_items)

        # 只在depth=2时获取第二层记忆
        if depth >= 2:
            # 获取相邻节点的记忆项
            for neighbor in neighbors:
                if node_data := self.get_dot(neighbor):
                    _, data = node_data
                    if "memory_items" in data:
                        # 直接使用完整的记忆内容
                        if memory_items := data["memory_items"]:
                            second_layer_items.append(memory_items)

        return first_layer_items, second_layer_items


    @property
    def dots(self):
        # 返回所有节点对应的 Memory_dot 对象
        return [self.get_dot(node) for node in self.G.nodes()]

    def forget_topic(self, topic):
        """随机删除指定话题中的一条记忆，如果话题没有记忆则移除该话题节点"""
        if topic not in self.G:
            return None

        # 获取话题节点数据
        node_data = self.G.nodes[topic]

        # 删除整个节点
        self.G.remove_node(topic)
        # 如果节点存在memory_items
        if "memory_items" in node_data:
            if memory_items := node_data["memory_items"]:
                return (
                    f"删除了节点 {topic} 的完整记忆: {memory_items[:50]}..."
                    if len(memory_items) > 50
                    else f"删除了节点 {topic} 的完整记忆: {memory_items}"
                )
        return None


# 海马体
class Hippocampus:
    def __init__(self):
        self.memory_graph = MemoryGraph()
        self.entorhinal_cortex: EntorhinalCortex = None  # type: ignore
        self.parahippocampal_gyrus: ParahippocampalGyrus = None  # type: ignore

    def initialize(self):
        # 初始化子组件
        self.entorhinal_cortex = EntorhinalCortex(self)
        self.parahippocampal_gyrus = ParahippocampalGyrus(self)
        # 从数据库加载记忆图
        self.entorhinal_cortex.sync_memory_from_db()

    def get_all_node_names(self) -> list:
        """获取记忆图中所有节点的名字列表"""
        return list(self.memory_graph.G.nodes())

    @staticmethod
    def calculate_node_hash(concept, memory_items) -> int:
        """计算节点的特征值"""
        # memory_items已经是str格式，直接按分隔符分割
        if memory_items:
            unique_items = {item.strip() for item in memory_items.split(" | ") if item.strip()}
        else:
            unique_items = set()

        # 使用frozenset来保证顺序一致性
        content = f"{concept}:{frozenset(unique_items)}"
        return hash(content)

    @staticmethod
    def calculate_edge_hash(source, target) -> int:
        """计算边的特征值"""
        # 直接使用元组，保证顺序一致性
        return hash((source, target))



# 负责海马体与其他部分的交互
class EntorhinalCortex:
    def __init__(self, hippocampus: Hippocampus):
        self.hippocampus = hippocampus
        self.memory_graph = hippocampus.memory_graph

    async def sync_memory_to_db(self):
        """将记忆图同步到数据库"""
        start_time = time.time()
        current_time = datetime.datetime.now().timestamp()

        # 获取数据库中所有节点和内存中所有节点
        db_nodes = {node.concept: node for node in GraphNodes.select()}
        memory_nodes = list(self.memory_graph.G.nodes(data=True))

        # 批量准备节点数据
        nodes_to_create = []
        nodes_to_update = []
        nodes_to_delete = set()

        # 处理节点
        for concept, data in memory_nodes:
            if not concept or not isinstance(concept, str):
                self.memory_graph.G.remove_node(concept)
                continue

            memory_items = data.get("memory_items", "")

            # 直接检查字符串是否为空，不需要分割成列表
            if not memory_items or memory_items.strip() == "":
                self.memory_graph.G.remove_node(concept)
                continue

            # 计算内存中节点的特征值
            memory_hash = self.hippocampus.calculate_node_hash(concept, memory_items)
            created_time = data.get("created_time", current_time)
            last_modified = data.get("last_modified", current_time)

            # memory_items直接作为字符串存储，不需要JSON序列化
            if not memory_items:
                continue

            # 获取权重属性
            weight = data.get("weight", 1.0)

            if concept not in db_nodes:
                nodes_to_create.append(
                    {
                        "concept": concept,
                        "memory_items": memory_items,
                        "weight": weight,
                        "hash": memory_hash,
                        "created_time": created_time,
                        "last_modified": last_modified,
                    }
                )
            else:
                db_node = db_nodes[concept]
                if db_node.hash != memory_hash:
                    nodes_to_update.append(
                        {
                            "concept": concept,
                            "memory_items": memory_items,
                            "weight": weight,
                            "hash": memory_hash,
                            "last_modified": last_modified,
                        }
                    )

        # 计算需要删除的节点
        memory_concepts = {concept for concept, _ in memory_nodes}
        nodes_to_delete = set(db_nodes.keys()) - memory_concepts

        # 批量处理节点
        if nodes_to_create:
            batch_size = 100
            for i in range(0, len(nodes_to_create), batch_size):
                batch = nodes_to_create[i : i + batch_size]
                GraphNodes.insert_many(batch).execute()

        if nodes_to_update:
            batch_size = 100
            for i in range(0, len(nodes_to_update), batch_size):
                batch = nodes_to_update[i : i + batch_size]
                for node_data in batch:
                    GraphNodes.update(**{k: v for k, v in node_data.items() if k != "concept"}).where(
                        GraphNodes.concept == node_data["concept"]
                    ).execute()

        if nodes_to_delete:
            GraphNodes.delete().where(GraphNodes.concept.in_(nodes_to_delete)).execute()  # type: ignore

        # 处理边的信息
        db_edges = list(GraphEdges.select())
        memory_edges = list(self.memory_graph.G.edges(data=True))

        # 创建边的哈希值字典
        db_edge_dict = {}
        for edge in db_edges:
            edge_hash = self.hippocampus.calculate_edge_hash(edge.source, edge.target)
            db_edge_dict[(edge.source, edge.target)] = {"hash": edge_hash, "strength": edge.strength}

        # 批量准备边数据
        edges_to_create = []
        edges_to_update = []

        # 处理边
        for source, target, data in memory_edges:
            edge_hash = self.hippocampus.calculate_edge_hash(source, target)
            edge_key = (source, target)
            strength = data.get("strength", 1)
            created_time = data.get("created_time", current_time)
            last_modified = data.get("last_modified", current_time)

            if edge_key not in db_edge_dict:
                edges_to_create.append(
                    {
                        "source": source,
                        "target": target,
                        "strength": strength,
                        "hash": edge_hash,
                        "created_time": created_time,
                        "last_modified": last_modified,
                    }
                )
            elif db_edge_dict[edge_key]["hash"] != edge_hash:
                edges_to_update.append(
                    {
                        "source": source,
                        "target": target,
                        "strength": strength,
                        "hash": edge_hash,
                        "last_modified": last_modified,
                    }
                )

        # 计算需要删除的边
        memory_edge_keys = {(source, target) for source, target, _ in memory_edges}
        edges_to_delete = set(db_edge_dict.keys()) - memory_edge_keys

        # 批量处理边
        if edges_to_create:
            batch_size = 100
            for i in range(0, len(edges_to_create), batch_size):
                batch = edges_to_create[i : i + batch_size]
                GraphEdges.insert_many(batch).execute()

        if edges_to_update:
            batch_size = 100
            for i in range(0, len(edges_to_update), batch_size):
                batch = edges_to_update[i : i + batch_size]
                for edge_data in batch:
                    GraphEdges.update(**{k: v for k, v in edge_data.items() if k not in ["source", "target"]}).where(
                        (GraphEdges.source == edge_data["source"]) & (GraphEdges.target == edge_data["target"])
                    ).execute()

        if edges_to_delete:
            for source, target in edges_to_delete:
                GraphEdges.delete().where((GraphEdges.source == source) & (GraphEdges.target == target)).execute()

        end_time = time.time()
        logger.info(f"[数据库] 同步完成，总耗时: {end_time - start_time:.2f}秒")
        logger.info(
            f"[数据库] 同步了 {len(nodes_to_create) + len(nodes_to_update)} 个节点和 {len(edges_to_create) + len(edges_to_update)} 条边"
        )

    async def resync_memory_to_db(self):
        """清空数据库并重新同步所有记忆数据"""
        start_time = time.time()
        logger.info("[数据库] 开始重新同步所有记忆数据...")

        # 清空数据库
        clear_start = time.time()
        GraphNodes.delete().execute()
        GraphEdges.delete().execute()
        clear_end = time.time()
        logger.info(f"[数据库] 清空数据库耗时: {clear_end - clear_start:.2f}秒")

        # 获取所有节点和边
        memory_nodes = list(self.memory_graph.G.nodes(data=True))
        memory_edges = list(self.memory_graph.G.edges(data=True))
        current_time = datetime.datetime.now().timestamp()

        # 批量准备节点数据
        nodes_data = []
        for concept, data in memory_nodes:
            memory_items = data.get("memory_items", "")

            # 直接检查字符串是否为空，不需要分割成列表
            if not memory_items or memory_items.strip() == "":
                self.memory_graph.G.remove_node(concept)
                continue

            # 计算内存中节点的特征值
            memory_hash = self.hippocampus.calculate_node_hash(concept, memory_items)
            created_time = data.get("created_time", current_time)
            last_modified = data.get("last_modified", current_time)

            # memory_items直接作为字符串存储，不需要JSON序列化
            if not memory_items:
                continue

            # 获取权重属性
            weight = data.get("weight", 1.0)

            nodes_data.append(
                {
                    "concept": concept,
                    "memory_items": memory_items,
                    "weight": weight,
                    "hash": memory_hash,
                    "created_time": created_time,
                    "last_modified": last_modified,
                }
            )

        # 批量插入节点
        if nodes_data:
            batch_size = 100
            for i in range(0, len(nodes_data), batch_size):
                batch = nodes_data[i : i + batch_size]
                GraphNodes.insert_many(batch).execute()

        # 批量准备边数据
        edges_data = []
        for source, target, data in memory_edges:
            try:
                edges_data.append(
                    {
                        "source": source,
                        "target": target,
                        "strength": data.get("strength", 1),
                        "hash": self.hippocampus.calculate_edge_hash(source, target),
                        "created_time": data.get("created_time", current_time),
                        "last_modified": data.get("last_modified", current_time),
                    }
                )
            except Exception as e:
                logger.error(f"准备边 {source}-{target} 数据时发生错误: {e}")
                continue

        # 批量插入边
        if edges_data:
            batch_size = 100
            for i in range(0, len(edges_data), batch_size):
                batch = edges_data[i : i + batch_size]
                GraphEdges.insert_many(batch).execute()

        end_time = time.time()
        logger.info(f"[数据库] 重新同步完成，总耗时: {end_time - start_time:.2f}秒")
        logger.info(f"[数据库] 同步了 {len(nodes_data)} 个节点和 {len(edges_data)} 条边")

    def sync_memory_from_db(self):
        """从数据库同步数据到内存中的图结构"""
        current_time = datetime.datetime.now().timestamp()
        need_update = False

        # 清空当前图
        self.memory_graph.G.clear()

        # 统计加载情况
        total_nodes = 0
        loaded_nodes = 0
        skipped_nodes = 0

        # 从数据库加载所有节点
        nodes = list(GraphNodes.select())
        total_nodes = len(nodes)

        for node in nodes:
            concept = node.concept
            try:
                # 处理空字符串或None的情况
                if not node.memory_items or node.memory_items.strip() == "":
                    logger.warning(f"节点 {concept} 的memory_items为空，跳过")
                    skipped_nodes += 1
                    continue

                # 直接使用memory_items
                memory_items = node.memory_items.strip()

                # 检查时间字段是否存在
                if not node.created_time or not node.last_modified:
                    # 更新数据库中的节点
                    update_data = {}
                    if not node.created_time:
                        update_data["created_time"] = current_time
                    if not node.last_modified:
                        update_data["last_modified"] = current_time

                    if update_data:
                        GraphNodes.update(**update_data).where(GraphNodes.concept == concept).execute()

                # 获取时间信息(如果不存在则使用当前时间)
                created_time = node.created_time or current_time
                last_modified = node.last_modified or current_time

                # 获取权重属性
                weight = node.weight if hasattr(node, "weight") and node.weight is not None else 1.0

                # 添加节点到图中
                self.memory_graph.G.add_node(
                    concept,
                    memory_items=memory_items,
                    weight=weight,
                    created_time=created_time,
                    last_modified=last_modified,
                )
                loaded_nodes += 1
            except Exception as e:
                logger.error(f"加载节点 {concept} 时发生错误: {e}")
                skipped_nodes += 1
                continue

        # 从数据库加载所有边
        edges = list(GraphEdges.select())
        for edge in edges:
            source = edge.source
            target = edge.target
            strength = edge.strength

            # 检查时间字段是否存在
            if not edge.created_time or not edge.last_modified:
                need_update = True
                # 更新数据库中的边
                update_data = {}
                if not edge.created_time:
                    update_data["created_time"] = current_time
                if not edge.last_modified:
                    update_data["last_modified"] = current_time

                GraphEdges.update(**update_data).where(
                    (GraphEdges.source == source) & (GraphEdges.target == target)
                ).execute()

            # 获取时间信息(如果不存在则使用当前时间)
            created_time = edge.created_time or current_time
            last_modified = edge.last_modified or current_time

            # 只有当源节点和目标节点都存在时才添加边
            if source in self.memory_graph.G and target in self.memory_graph.G:
                self.memory_graph.G.add_edge(
                    source, target, strength=strength, created_time=created_time, last_modified=last_modified
                )

        if need_update:
            logger.info("[数据库] 已为缺失的时间字段进行补充")

        # 输出加载统计信息
        logger.info(
            f"[数据库] 记忆加载完成: 总计 {total_nodes} 个节点, 成功加载 {loaded_nodes} 个, 跳过 {skipped_nodes} 个"
        )


# 负责记忆管理
class ParahippocampalGyrus:
    def __init__(self, hippocampus: Hippocampus):
        self.hippocampus = hippocampus
        self.memory_graph = hippocampus.memory_graph


class HippocampusManager:
    def __init__(self):
        self._hippocampus: Hippocampus = None  # type: ignore
        self._initialized = False

    def initialize(self):
        """初始化海马体实例"""
        if self._initialized:
            return self._hippocampus

        self._hippocampus = Hippocampus()
        self._hippocampus.initialize()
        self._initialized = True

        # 输出记忆图统计信息
        memory_graph = self._hippocampus.memory_graph.G
        node_count = len(memory_graph.nodes())
        edge_count = len(memory_graph.edges())

        logger.info(f"""
                    --------------------------------
                    记忆系统参数配置:
                    记忆图统计信息: 节点数量: {node_count}, 连接数量: {edge_count}
                    --------------------------------""")  # noqa: E501

        return self._hippocampus

    def get_hippocampus(self):
        if not self._initialized:
            raise RuntimeError("HippocampusManager 尚未初始化，请先调用 initialize 方法")
        return self._hippocampus

    def get_all_node_names(self) -> list:
        """获取所有节点名称的公共接口"""
        if not self._initialized:
            raise RuntimeError("HippocampusManager 尚未初始化，请先调用 initialize 方法")
        return self._hippocampus.get_all_node_names()


# 创建全局实例
hippocampus_manager = HippocampusManager()
