#!/bin/sh
set -e  # 遇到任何错误立即退出

# 定义常量
TEMPLATE_DIR="./template"
CONFIG_DIR="./config"
TARGET_ENV_FILE="./.env"

# 步骤 1: 创建 config 目录
if [ ! -d "$CONFIG_DIR" ]; then
    echo "🛠️ 创建配置目录: $CONFIG_DIR"
    mkdir -p "$CONFIG_DIR"
    chmod 755 "$CONFIG_DIR"  # 设置目录权限（按需修改）
else
    echo "ℹ️ 配置目录已存在，跳过创建: $CONFIG_DIR"
fi

# 步骤 2: 复制 bot 配置文件
BOT_TEMPLATE="$TEMPLATE_DIR/bot_config_template.toml"
BOT_CONFIG="$CONFIG_DIR/bot_config.toml"

if [ -f "$BOT_TEMPLATE" ]; then
    if [ ! -f "$BOT_CONFIG" ]; then
        echo "📄 生成 Bot 配置文件: $BOT_CONFIG"
        cp "$BOT_TEMPLATE" "$BOT_CONFIG"
        chmod 644 "$BOT_CONFIG"  # 设置文件权限（按需修改）
    else
        echo "ℹ️ Bot 配置文件已存在，跳过生成: $BOT_CONFIG"
    fi
else
    echo "❌ 错误：模板文件不存在: $BOT_TEMPLATE" >&2
    exit 1
fi

# 步骤 3: 复制环境文件
ENV_TEMPLATE="$TEMPLATE_DIR/template.env"
ENV_TARGET="$TARGET_ENV_FILE"

if [ -f "$ENV_TEMPLATE" ]; then
    if [ ! -f "$ENV_TARGET" ]; then
        echo "🔧 生成环境配置文件: $ENV_TARGET"
        cp "$ENV_TEMPLATE" "$ENV_TARGET"
        chmod 600 "$ENV_TARGET"  # 敏感文件建议更严格权限
    else
        echo "ℹ️ 环境文件已存在，跳过生成: $ENV_TARGET"
    fi
else
    echo "❌ 错误：模板文件不存在: $ENV_TEMPLATE" >&2
    exit 1
fi

echo "✅ 所有初始化完成！"

# 执行 Docker CMD 命令
exec "$@"