import os
import nonebot
from nonebot.adapters.onebot.v11 import Adapter
from dotenv import load_dotenv
from loguru import logger

    # 加载全局环境变量
root_dir = os.path.dirname(os.path.abspath(__file__))
env_path=os.path.join(root_dir, "config",'.env')

logger.info(f"尝试从 {env_path} 加载环境变量配置")
if os.path.exists(env_path):
    load_dotenv(env_path)
    logger.success("成功加载环境变量配置")
else:
    logger.error(f"环境变量配置文件不存在: {env_path}")

# 初始化 NoneBot
nonebot.init(
    # napcat 默认使用 8080 端口
    websocket_port=8080,
    # 设置日志级别
    log_level="INFO",
    # 设置超级用户
    superusers={"你的QQ号"},
    # TODO: 这样写会忽略环境变量需要优化 https://nonebot.dev/docs/appendices/config
    _env_file=env_path
)

# 注册适配器
driver = nonebot.get_driver()
driver.register_adapter(Adapter)

# 加载插件
nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    nonebot.run()