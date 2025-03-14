import requests
import time
import uuid
import platform
import os
import json
from loguru import logger
import asyncio

# UUID文件路径
UUID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client_uuid.json")

# 生成或获取客户端唯一ID
def get_unique_id():
    # 检查是否已经有保存的UUID
    if os.path.exists(UUID_FILE):
        try:
            with open(UUID_FILE, 'r') as f:
                data = json.load(f)
                if 'client_id' in data:
                    print("从本地文件读取客户端ID")
                    return data['client_id']
        except (json.JSONDecodeError, IOError) as e:
            print(f"读取UUID文件出错: {e}，将生成新的UUID")
    
    # 如果没有保存的UUID或读取出错，则生成新的
    client_id = generate_unique_id()
    
    # 保存UUID到文件
    try:
        with open(UUID_FILE, 'w') as f:
            json.dump({'client_id': client_id}, f)
        print("已保存新生成的客户端ID到本地文件")
    except IOError as e:
        print(f"保存UUID时出错: {e}")
    
    return client_id

# 生成客户端唯一ID
def generate_unique_id():
    # 结合主机名、系统信息和随机UUID生成唯一ID
    system_info = platform.system()
    unique_id = f"{system_info}-{uuid.uuid4()}"
    return unique_id

def send_heartbeat(server_url, client_id):
    """向服务器发送心跳"""
    sys = platform.system()
    try:
        headers = {
            'Client-ID': client_id,
            'User-Agent': f'HeartbeatClient/{client_id[:8]}'
        }
        data = json.dumps({
            'system': sys
        })
        response = requests.post(
            f"{server_url}/api/clients",
            headers=headers,
            data=data
        )
        
        if response.status_code == 201:
            data = response.json()
            logger.debug(f"心跳发送成功。服务器响应: {data}")
            return True
        else:
            logger.debug(f"心跳发送失败。状态码: {response.status_code}")
            return False
    
    except requests.RequestException as e:
        logger.debug(f"发送心跳时出错: {e}")
        return False

async def main():
    # 配置
    SERVER_URL = "http://hyybuth.xyz:10058"  # 更改为你的服务器地址
    HEARTBEAT_INTERVAL = 300  # 5分钟（秒）
    
    # 获取或生成客户端ID
    client_id = get_unique_id()
    logger.debug(f"客户端已启动，ID: {client_id}")
    
    # 主心跳循环
    try:
        while True:
            if send_heartbeat(SERVER_URL, client_id):
                print(f"{HEARTBEAT_INTERVAL}秒后发送下一次心跳...")
            else:
                print(f"{HEARTBEAT_INTERVAL}秒后重试...")
            
            await asyncio.sleep(HEARTBEAT_INTERVAL)
    
    except KeyboardInterrupt:
        print("用户已停止客户端")
    except Exception as e:
        print(f"发生意外错误: {e}")

if __name__ == "__main__":
    asyncio.run(main())
