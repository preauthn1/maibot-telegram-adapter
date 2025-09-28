# -*- coding: utf-8 -*-
import random
from typing import List

from src.manager.async_task_manager import AsyncTask
from src.chat.memory_system.Hippocampus import hippocampus_manager
from src.chat.memory_system.Memory_chest import global_memory_chest
from src.common.logger import get_logger

logger = get_logger("hippocampus_to_memory_chest")


class HippocampusToMemoryChestTask(AsyncTask):
    """海马体到记忆仓库的转换任务
    
    每60秒随机选择5个海马体节点，将内容拼接为content，
    然后根据memory_chest的格式生成标题并存储
    """
    
    def __init__(self):
        super().__init__(
            task_name="Hippocampus to Memory Chest Task",
            wait_before_start=60,  # 启动后等待60秒再开始
            run_interval=60  # 每60秒运行一次
        )
        
    async def run(self):
        """执行转换任务"""
        try:
            logger.info("[海马体转换] 开始执行海马体到记忆仓库的转换任务")
            
            # 检查海马体管理器是否已初始化
            if not hippocampus_manager._initialized:
                logger.warning("[海马体转换] 海马体管理器尚未初始化，跳过本次转换")
                return
                
            # 获取海马体实例
            hippocampus = hippocampus_manager.get_hippocampus()
            memory_graph = hippocampus.memory_graph.G
            
            # 获取所有节点
            all_nodes = list(memory_graph.nodes())
            
            if len(all_nodes) < 5:
                logger.info(f"[海马体转换] 当前只有 {len(all_nodes)} 个节点，少于5个，跳过本次转换")
                return
                
            # 随机选择5个节点
            selected_nodes = random.sample(all_nodes, 5)
            logger.info(f"[海马体转换] 随机选择了 {len(selected_nodes)} 个节点: {selected_nodes}")
            
            # 拼接节点内容
            content_parts = []
            for node in selected_nodes:
                node_data = memory_graph.nodes[node]
                memory_items = node_data.get("memory_items", "")
                
                if memory_items and memory_items.strip():
                    # 添加节点名称和内容
                    content_parts.append(f"【{node}】{memory_items}")
                else:
                    logger.debug(f"[海马体转换] 节点 {node} 没有记忆内容，跳过")
                    
            if not content_parts:
                logger.info("[海马体转换] 没有找到有效的记忆内容，跳过本次转换")
                return
                
            # 拼接所有内容
            combined_content = "\n\n".join(content_parts)
            logger.info(f"[海马体转换] 拼接完成，内容长度: {len(combined_content)} 字符")
            
            # 生成标题并存储到记忆仓库
            success = await self._save_to_memory_chest(combined_content)
            
            # 如果保存成功，删除已转换的节点
            if success:
                await self._remove_converted_nodes(selected_nodes)
            
            logger.info("[海马体转换] 转换任务完成")
            
        except Exception as e:
            logger.error(f"[海马体转换] 执行转换任务时发生错误: {e}", exc_info=True)
    
    async def _save_to_memory_chest(self, content: str) -> bool:
        """将内容保存到记忆仓库
        
        Args:
            content: 要保存的内容
            
        Returns:
            bool: 保存是否成功
        """
        try:
            # 使用Memory_chest的LLMRequest生成标题
            title_prompt = f"""
请为以下内容生成一个描述全面的标题，要求描述内容的主要概念和事件：
{content}

请只输出标题，不要输出其他内容：
"""
            
            # 使用Memory_chest的LLM模型生成标题
            title, (reasoning_content, model_name, tool_calls) = await global_memory_chest.LLMRequest_build.generate_response_async(title_prompt)
            
            if title and title.strip():
                # 保存到数据库
                from src.common.database.database_model import MemoryChest as MemoryChestModel
                
                MemoryChestModel.create(
                    title=title.strip(),
                    content=content
                )
                
                logger.info(f"[海马体转换] 已保存到记忆仓库，标题: {title.strip()}")
                return True
            else:
                logger.warning("[海马体转换] 生成标题失败，跳过保存")
                return False
                
        except Exception as e:
            logger.error(f"[海马体转换] 保存到记忆仓库时发生错误: {e}", exc_info=True)
            return False
    
    async def _remove_converted_nodes(self, nodes_to_remove: List[str]):
        """删除已转换的海马体节点
        
        Args:
            nodes_to_remove: 要删除的节点列表
        """
        try:
            # 获取海马体实例
            hippocampus = hippocampus_manager.get_hippocampus()
            memory_graph = hippocampus.memory_graph.G
            
            removed_count = 0
            for node in nodes_to_remove:
                if node in memory_graph:
                    # 删除节点（这会自动删除相关的边）
                    memory_graph.remove_node(node)
                    removed_count += 1
                    logger.info(f"[海马体转换] 已删除节点: {node}")
                else:
                    logger.debug(f"[海马体转换] 节点 {node} 不存在，跳过删除")
            
            # 同步到数据库
            if removed_count > 0:
                await hippocampus.entorhinal_cortex.sync_memory_to_db()
                logger.info(f"[海马体转换] 已删除 {removed_count} 个节点并同步到数据库")
            else:
                logger.info("[海马体转换] 没有节点需要删除")
                
        except Exception as e:
            logger.error(f"[海马体转换] 删除节点时发生错误: {e}", exc_info=True)
