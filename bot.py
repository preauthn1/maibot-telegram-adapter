import os
import nonebot
from nonebot.adapters.onebot.v11 import Adapter
from dotenv import load_dotenv
from loguru import logger

'''彩蛋'''
from colorama import init, Fore
init()
text = "多年以后，面对行刑队，张三将会回想起他2023年在会议上讨论人工智能的那个下午"
rainbow_colors = [Fore.RED, Fore.YELLOW, Fore.GREEN, Fore.CYAN, Fore.BLUE, Fore.MAGENTA]
rainbow_text = ""
for i, char in enumerate(text):
    rainbow_text += rainbow_colors[i % len(rainbow_colors)] + char
print(rainbow_text)
'''彩蛋'''

# 首先加载基础环境变量
if os.path.exists(".env"):
    load_dotenv(".env")
    logger.success("成功加载基础环境变量配置")
else:
    logger.error("基础环境变量配置文件 .env 不存在")
    exit(1)
# 根据 ENVIRONMENT 加载对应的环境配置
env = os.getenv("ENVIRONMENT")
env_file = f".env.{env}"
    
if env_file == ".env.dev" and os.path.exists(env_file):
    logger.success("加载开发环境变量配置")
    load_dotenv(env_file, override=True)  # override=True 允许覆盖已存在的环境变量
elif os.path.exists(".env.prod"):
    logger.success("加载环境变量配置")
    load_dotenv(env_file, override=True)  # override=True 允许覆盖已存在的环境变量
else:
    logger.error(f"{env}对应的环境配置文件{env_file}不存在,请修改.env文件中的ENVIRONMENT变量为 prod.")
    exit(1)

nonebot.init(
    # 从环境变量中读取配置
    websocket_port=os.getenv("PORT", 8080),
    host=os.getenv("HOST", "127.0.0.1"),
    log_level="INFO",
    # 添加自定义配置
    mongodb_host=os.getenv("MONGODB_HOST", "127.0.0.1"),
    mongodb_port=os.getenv("MONGODB_PORT", 27017),
    database_name=os.getenv("DATABASE_NAME", "MegBot"),
    mongodb_username=os.getenv("MONGODB_USERNAME", ""),
    mongodb_password=os.getenv("MONGODB_PASSWORD", ""),
    mongodb_auth_source=os.getenv("MONGODB_AUTH_SOURCE", ""),
    # API相关配置
    chat_any_where_key=os.getenv("CHAT_ANY_WHERE_KEY", ""),
    siliconflow_key=os.getenv("SILICONFLOW_KEY", ""),
    chat_any_where_base_url=os.getenv("CHAT_ANY_WHERE_BASE_URL", "https://api.chatanywhere.tech/v1"),
    siliconflow_base_url=os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1/"),
    deep_seek_key=os.getenv("DEEP_SEEK_KEY", ""),
    deep_seek_base_url=os.getenv("DEEP_SEEK_BASE_URL", "https://api.deepseek.com/v1"),
    # 插件配置
    plugins=os.getenv("PLUGINS", ["src2.plugins.chat"])
)

# 注册适配器
driver = nonebot.get_driver()
driver.register_adapter(Adapter)

# 加载插件
nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    nonebot.run()