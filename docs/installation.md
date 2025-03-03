# 🔧 安装与配置指南

## 部署方式

### 🐳 Docker部署（推荐）

1. 获取配置文件：
```bash
wget https://raw.githubusercontent.com/SengokuCola/MaiMBot/main/docker-compose.yml
```

2. 启动服务：
```bash
NAPCAT_UID=$(id -u) NAPCAT_GID=$(id -g) docker compose up -d
```

3. 修改配置后重启：
```bash
NAPCAT_UID=$(id -u) NAPCAT_GID=$(id -g) docker compose restart
```

### 📦 手动部署

1. **环境准备**
```bash
# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux
venv\\Scripts\\activate   # Windows

# 安装依赖
pip install -r requirements.txt
```

2. **配置MongoDB**
- 安装并启动MongoDB服务
- 默认连接本地27017端口

3. **配置NapCat**
- 安装并登录NapCat
- 添加反向WS：`ws://localhost:8080/onebot/v11/ws`

4. **配置文件设置**
- 复制并修改环境配置：`.env.prod`
- 复制并修改机器人配置：`bot_config.toml`

5. **启动服务**
```bash
nb run
```

6. **其他组件**
- `run_thingking.bat`: 启动可视化推理界面（未完善）和消息队列预览
- `knowledge.bat`: 将`/data/raw_info`下的文本文档载入数据库

## ⚙️ 配置说明

### 环境配置 (.env.prod)
```ini
# API配置（必填）
SILICONFLOW_KEY=your_key
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1/
DEEP_SEEK_KEY=your_key
DEEP_SEEK_BASE_URL=https://api.deepseek.com/v1

# 服务配置
HOST=127.0.0.1
PORT=8080

# 数据库配置
MONGODB_HOST=127.0.0.1
MONGODB_PORT=27017
DATABASE_NAME=MegBot
```

### 机器人配置 (bot_config.toml)
```toml
[bot]
qq = "你的机器人QQ号"
nickname = "麦麦"

[message]
max_context_size = 15
emoji_chance = 0.2

[response]
api_using = "siliconflow"  # 或 "deepseek"

[others]
enable_advance_output = false  # 是否启用详细日志输出

[groups]
talk_allowed = []      # 允许回复的群号列表
talk_frequency_down = []   # 降低回复频率的群号列表
ban_user_id = []      # 禁止回复的用户QQ号列表
```

## ⚠️ 注意事项

- 目前部署方案仍在测试中，可能存在未知问题
- 配置文件中的API密钥请妥善保管，不要泄露
- 建议先在测试环境中运行，确认无误后再部署到生产环境 