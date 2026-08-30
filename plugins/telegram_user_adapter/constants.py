"""Telegram 真人账号适配器共享常量。"""

# 网关组件名称
TELEGRAM_USER_GATEWAY_NAME = "telegram_user_gateway"

# 平台标识。与 Bot API 适配器保持一致，便于复用主程序既有的 telegram 平台逻辑。
PLATFORM_NAME = "telegram"

# 配置结构版本
SUPPORTED_CONFIG_VERSION = "0.1.0"

# 默认名单模式
DEFAULT_CHAT_LIST_TYPE = "whitelist"

# 拟人化默认参数
DEFAULT_TYPING_CPS = 6.0
DEFAULT_MIN_THINK_DELAY = 0.8
DEFAULT_MAX_TYPING_DELAY = 12.0
DEFAULT_READ_DELAY = 0.6

# 会话文件名（存放在插件 data 目录下）
SESSION_FILE_NAME = "telegram_user.session"
