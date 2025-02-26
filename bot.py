import nonebot
from nonebot.adapters.onebot.v11 import Adapter

# 初始化 NoneBot
nonebot.init(
    # napcat 默认使用 8080 端口
    websocket_port=8080,
    # 设置日志级别
    log_level="INFO",
    # 设置超级用户
    superusers={"你的QQ号"}
)

# 注册适配器
driver = nonebot.get_driver()
driver.register_adapter(Adapter)

# 加载插件
nonebot.load_plugins("src/plugins")

if __name__ == "__main__":
    nonebot.run()