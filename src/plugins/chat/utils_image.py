import io
from PIL import Image
import hashlib
import time
import os
from ...common.database import Database
from .config import BotConfig
import zlib  # 用于 CRC32
import base64

bot_config = BotConfig.load_config()


def storage_image(image_data: bytes,type: str, max_size: int = 200) -> bytes:
    if type == 'image':
        return storage_compress_image(image_data, max_size)
    elif type == 'emoji':
        return storage_emoji(image_data)
    else:
        raise ValueError(f"不支持的图片类型: {type}")


def storage_compress_image(image_data: bytes, max_size: int = 200) -> bytes:
    """
    压缩图片到指定大小（单位：KB）并在数据库中记录图片信息
    Args:
        image_data: 图片字节数据
        group_id: 群组ID
        user_id: 用户ID
        max_size: 最大文件大小（KB）
    """
    try:
        # 使用 CRC32 计算哈希值
        hash_value = format(zlib.crc32(image_data) & 0xFFFFFFFF, 'x')
        
        # 确保图片目录存在
        images_dir = "data/images"
        os.makedirs(images_dir, exist_ok=True)
        
        # 连接数据库
        db = Database(
            host=bot_config.MONGODB_HOST,
            port=bot_config.MONGODB_PORT,
            db_name=bot_config.DATABASE_NAME,
            username=bot_config.MONGODB_USERNAME,
            password=bot_config.MONGODB_PASSWORD,
            auth_source=bot_config.MONGODB_AUTH_SOURCE
        )
        
        # 检查是否已存在相同哈希值的图片
        collection = db.db['images']
        existing_image = collection.find_one({'hash': hash_value})
        
        if existing_image:
            print(f"\033[1;33m[提示]\033[0m 发现重复图片，使用已存在的文件: {existing_image['path']}")
            return image_data

        # 将字节数据转换为图片对象
        img = Image.open(io.BytesIO(image_data))
        
        # 如果是动图，直接返回原图
        if getattr(img, 'is_animated', False):
            return image_data
            
        # 计算当前大小（KB）
        current_size = len(image_data) / 1024
        
        # 如果已经小于目标大小，直接使用原图
        if current_size <= max_size:
            compressed_data = image_data
        else:
            # 压缩逻辑
            # 先缩放到50%
            new_width = int(img.width * 0.5)
            new_height = int(img.height * 0.5)
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 如果缩放后的最大边长仍然大于400，继续缩放
            max_dimension = 400
            max_current = max(new_width, new_height)
            if max_current > max_dimension:
                ratio = max_dimension / max_current
                new_width = int(new_width * ratio)
                new_height = int(new_height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 转换为RGB模式（去除透明通道）
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # 使用固定质量参数压缩
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=85, optimize=True)
            compressed_data = output.getvalue()
        
        # 生成文件名（使用时间戳和哈希值确保唯一性）
        timestamp = int(time.time())
        filename = f"{timestamp}_{hash_value}.jpg"
        image_path = os.path.join(images_dir, filename)
        
        # 保存文件
        with open(image_path, "wb") as f:
            f.write(compressed_data)
            
        print(f"\033[1;32m[成功]\033[0m 保存图片到: {image_path}")
        
        try:
            # 准备数据库记录
            image_record = {
                'filename': filename,
                'path': image_path,
                'size': len(compressed_data) / 1024,
                'timestamp': timestamp,
                'width': img.width,
                'height': img.height,
                'description': '',
                'tags': [],
                'type': 'image',
                'hash': hash_value
            }
            
            # 保存记录
            collection.insert_one(image_record)
            print(f"\033[1;32m[成功]\033[0m 保存图片记录到数据库")
            
        except Exception as db_error:
            print(f"\033[1;31m[错误]\033[0m 数据库操作失败: {str(db_error)}")
            
        return compressed_data
        
    except Exception as e:
        print(f"\033[1;31m[错误]\033[0m 压缩图片失败: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return image_data 

def storage_emoji(image_data: bytes) -> bytes:
    """
    存储表情包到本地文件夹
    Args:
        image_data: 图片字节数据
        group_id: 群组ID（仅用于日志）
        user_id: 用户ID（仅用于日志）
    Returns:
        bytes: 原始图片数据
    """
    try:
        # 使用 CRC32 计算哈希值
        hash_value = format(zlib.crc32(image_data) & 0xFFFFFFFF, 'x')
        
        # 确保表情包目录存在
        emoji_dir = "data/emoji"
        os.makedirs(emoji_dir, exist_ok=True)
        
        # 检查是否已存在相同哈希值的文件
        for filename in os.listdir(emoji_dir):
            if hash_value in filename:
                # print(f"\033[1;33m[提示]\033[0m 发现重复表情包: {filename}")
                return image_data
        
        # 生成文件名
        timestamp = int(time.time())
        filename = f"{timestamp}_{hash_value}.jpg"
        emoji_path = os.path.join(emoji_dir, filename)
        
        # 直接保存原始文件
        with open(emoji_path, "wb") as f:
            f.write(image_data)
            
        print(f"\033[1;32m[成功]\033[0m 保存表情包到: {emoji_path}")
        return image_data
        
    except Exception as e:
        print(f"\033[1;31m[错误]\033[0m 保存表情包失败: {str(e)}")
        return image_data 
    

def storage_image(image_data: bytes) -> bytes:
    """
    存储图片到本地文件夹
    Args:
        image_data: 图片字节数据
        group_id: 群组ID（仅用于日志）
        user_id: 用户ID（仅用于日志）
    Returns:
        bytes: 原始图片数据
    """
    try:
        # 使用 CRC32 计算哈希值
        hash_value = format(zlib.crc32(image_data) & 0xFFFFFFFF, 'x')
        
        # 确保表情包目录存在
        image_dir = "data/image"
        os.makedirs(image_dir, exist_ok=True)
        
        # 检查是否已存在相同哈希值的文件
        for filename in os.listdir(image_dir):
            if hash_value in filename:
                # print(f"\033[1;33m[提示]\033[0m 发现重复表情包: {filename}")
                return image_data
        
        # 生成文件名
        timestamp = int(time.time())
        filename = f"{timestamp}_{hash_value}.jpg"
        image_path = os.path.join(image_dir, filename)
        
        # 直接保存原始文件
        with open(image_path, "wb") as f:
            f.write(image_data)
            
        print(f"\033[1;32m[成功]\033[0m 保存图片到: {image_path}")
        return image_data
        
    except Exception as e:
        print(f"\033[1;31m[错误]\033[0m 保存图片失败: {str(e)}")
        return image_data 