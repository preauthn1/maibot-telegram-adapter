# 🐳 Docker 部署指南

## 部署步骤（推荐，但不一定是最新）

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

## ⚠️ 注意事项

- 目前部署方案仍在测试中，可能存在未知问题
- 配置文件中的API密钥请妥善保管，不要泄露
- 建议先在测试环境中运行，确认无误后再部署到生产环境 