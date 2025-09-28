# -*- coding: utf-8 -*-
import asyncio
import random
import re
from typing import List

from src.manager.async_task_manager import AsyncTask
from src.chat.memory_system.Hippocampus import hippocampus_manager
from src.common.logger import get_logger

logger = get_logger("hippocampus_to_memory_chest")


class HippocampusToMemoryChestTask(AsyncTask):
    """海马体到记忆仓库的转换任务
    
    每10秒执行一次转换，每次最多处理50批，每批15个节点，
    当没有新节点时停止任务运行
    """
    
    def __init__(self):
        super().__init__(
            task_name="Hippocampus to Memory Chest Task",
            wait_before_start=5,  # 启动后等待5秒再开始
            run_interval=10  # 每10秒运行一次
        )
        self.task_stopped = False  # 标记任务是否已停止
    
    async def start_task(self, abort_flag: asyncio.Event):
        """重写start_task方法，支持任务停止"""
        if self.wait_before_start > 0:
            # 等待指定时间后开始任务
            await asyncio.sleep(self.wait_before_start)

        while not abort_flag.is_set() and not self.task_stopped:
            await self.run()
            if self.run_interval > 0:
                await asyncio.sleep(self.run_interval)
            else:
                break
        
        if self.task_stopped:
            logger.info("[海马体转换] 任务已完全停止，不再执行")
        
    async def run(self):
        """执行转换任务"""
        try:
            # 检查任务是否已停止
            if self.task_stopped:
                logger.info("[海马体转换] 任务已停止，跳过执行")
                return
                
            logger.info("[海马体转换] 开始执行海马体到记忆仓库的转换任务")
            
            # 检查海马体管理器是否已初始化
            if not hippocampus_manager._initialized:
                logger.warning("[海马体转换] 海马体管理器尚未初始化，跳过本次转换")
                return
                
            # 获取海马体实例
            hippocampus = hippocampus_manager.get_hippocampus()
            memory_graph = hippocampus.memory_graph.G
            
            # 执行10批转换
            total_processed = 0
            total_success = 0
            
            for batch_num in range(1, 51):  # 执行10批
                logger.info(f"[海马体转换] 开始执行第 {batch_num} 批转换")
                
                # 检查剩余节点
                remaining_nodes = list(memory_graph.nodes())
                if len(remaining_nodes) == 0:
                    logger.info(f"[海马体转换] 第 {batch_num} 批：没有剩余节点，停止任务运行")
                    self.task_stopped = True
                    break
                
                # 如果剩余节点不足10个，使用所有剩余节点
                if len(remaining_nodes) < 15:
                    selected_nodes = remaining_nodes
                    logger.info(f"[海马体转换] 第 {batch_num} 批：剩余节点不足10个（{len(remaining_nodes)}个），使用所有剩余节点")
                else:
                    # 随机选择10个节点
                    selected_nodes = random.sample(remaining_nodes, 15)
                logger.info(f"[海马体转换] 第 {batch_num} 批：选择了 {len(selected_nodes)} 个节点")
                
                # 拼接节点内容
                content_parts = []
                valid_nodes = []
                
                for node in selected_nodes:
                    node_data = memory_graph.nodes[node]
                    memory_items = node_data.get("memory_items", "")
                    
                    if memory_items and memory_items.strip():
                        # 添加节点名称和内容
                        content_parts.append(f"【{node}】{memory_items}")
                        valid_nodes.append(node)
                    else:
                        logger.debug(f"[海马体转换] 第 {batch_num} 批：节点 {node} 没有记忆内容，跳过")
                        
                if not content_parts:
                    logger.info(f"[海马体转换] 第 {batch_num} 批：没有找到有效的记忆内容，跳过")
                    continue
                    
                # 拼接所有内容
                combined_content = "\n\n".join(content_parts)
                logger.info(f"[海马体转换] 第 {batch_num} 批：拼接完成，内容长度: {len(combined_content)} 字符")
                
                # 生成标题并存储到记忆仓库
                success = await self._save_to_memory_chest(combined_content, batch_num)
                
                # 如果保存成功，删除已转换的节点
                if success:
                    await self._remove_converted_nodes(valid_nodes)
                    total_success += 1
                    logger.info(f"[海马体转换] 第 {batch_num} 批：转换成功")
                else:
                    logger.warning(f"[海马体转换] 第 {batch_num} 批：转换失败")
                
                total_processed += 1
                
                # 批次间短暂休息，避免过于频繁的数据库操作
                if batch_num < 10:
                    await asyncio.sleep(0.1)
            
            logger.info(f"[海马体转换] 本次执行完成：共处理 {total_processed} 批，成功 {total_success} 批")
            
            logger.info("[海马体转换] 转换任务完成")
            
        except Exception as e:
            logger.error(f"[海马体转换] 执行转换任务时发生错误: {e}", exc_info=True)
    
    async def _save_to_memory_chest(self, content: str, batch_num: int = 1) -> bool:
        """将内容保存到记忆仓库
        
        Args:
            content: 要保存的内容
            batch_num: 批次号
            
        Returns:
            bool: 保存是否成功
        """
        try:
            # 从内容中提取节点名称作为标题
            title = self._generate_title_from_content(content, batch_num)
            
            if title:
                # 保存到数据库
                from src.common.database.database_model import MemoryChest as MemoryChestModel
                
                MemoryChestModel.create(
                    title=title,
                    content=content
                )
                
                logger.info(f"[海马体转换] 第 {batch_num} 批：已保存到记忆仓库，标题: {title}")
                return True
            else:
                logger.warning("[海马体转换] 生成标题失败，跳过保存")
                return False
                
        except Exception as e:
            logger.error(f"[海马体转换] 保存到记忆仓库时发生错误: {e}", exc_info=True)
            return False
    
    def _generate_title_from_content(self, content: str, batch_num: int = 1) -> str:
        """从内容中提取节点名称生成标题
        
        Args:
            content: 拼接的内容
            batch_num: 批次号
            
        Returns:
            str: 生成的标题
        """
        try:
            # 提取所有【节点名称】中的节点名称
            node_pattern = r'【([^】]+)】'
            nodes = re.findall(node_pattern, content)
            
            if nodes:
                # 去重并限制数量（最多显示前5个）
                unique_nodes = list(dict.fromkeys(nodes))[:5]
                title = f"关于{','.join(unique_nodes)}的记忆"
                return title
            else:
                logger.warning("[海马体转换] 无法从内容中提取节点名称")
                return ""
                
        except Exception as e:
            logger.error(f"[海马体转换] 生成标题时发生错误: {e}", exc_info=True)
            return ""
    
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
