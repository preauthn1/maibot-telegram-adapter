from fastapi import FastAPI, HTTPException
from typing import Dict, Any, Callable, List
from src.common.logger import get_module_logger
import aiohttp
import asyncio
import uvicorn
import os
import traceback

logger = get_module_logger("api")


class BaseMessageAPI:
    def __init__(self, host: str = "0.0.0.0", port: int = 18000):
        self.app = FastAPI()
        self.host = host
        self.port = port
        self.message_handlers: List[Callable] = []
        self.cache = []
        self._setup_routes()
        self._running = False

    def _setup_routes(self):
        """设置基础路由"""

        @self.app.post("/api/message")
        async def handle_message(message: Dict[str, Any]):
            try:
                # 创建后台任务处理消息
                asyncio.create_task(self._background_message_handler(message))
                return {"status": "success"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e)) from e

    async def _background_message_handler(self, message: Dict[str, Any]):
        """后台处理单个消息"""
        try:
            await self.process_single_message(message)
        except Exception as e:
            logger.error(f"Background message processing failed: {str(e)}")
            logger.error(traceback.format_exc())

    def register_message_handler(self, handler: Callable):
        """注册消息处理函数"""
        self.message_handlers.append(handler)

    async def send_message(self, url: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """发送消息到指定端点"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=data, headers={"Content-Type": "application/json"}) as response:
                    return await response.json()
            except Exception:
                # logger.error(f"发送消息失败: {str(e)}")
                pass

    async def process_single_message(self, message: Dict[str, Any]):
        """处理单条消息"""
        tasks = []
        for handler in self.message_handlers:
            try:
                tasks.append(handler(message))
            except Exception as e:
                logger.error(str(e))
                logger.error(traceback.format_exc())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def run_sync(self):
        """同步方式运行服务器"""
        uvicorn.run(self.app, host=self.host, port=self.port)

    async def run(self):
        """异步方式运行服务器"""
        config = uvicorn.Config(self.app, host=self.host, port=self.port, loop="asyncio")
        self.server = uvicorn.Server(config)
        try:
            await self.server.serve()
        except KeyboardInterrupt as e:
            await self.stop()
            raise KeyboardInterrupt from e

    async def start_server(self):
        """启动服务器的异步方法"""
        if not self._running:
            self._running = True
            await self.run()

    async def stop(self):
        """停止服务器"""
        if hasattr(self, "server"):
            self._running = False
            # 正确关闭 uvicorn 服务器
            self.server.should_exit = True
            await self.server.shutdown()
            # 等待服务器完全停止
            if hasattr(self.server, "started") and self.server.started:
                await self.server.main_loop()
            # 清理处理程序
            self.message_handlers.clear()

    def start(self):
        """启动服务器的便捷方法"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.start_server())
        except KeyboardInterrupt:
            pass
        finally:
            loop.close()


global_api = BaseMessageAPI(host=os.environ["HOST"], port=int(os.environ["PORT"]))
