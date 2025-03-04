import subprocess
import threading
import queue
import os
import time
from typing import Dict
from .message import Message_Thinking

class MessageVisualizer:
    def __init__(self):
        self.process = None
        self.message_queue = queue.Queue()
        self.is_running = False
        self.content_file = "message_queue_content.txt"
        
    def start(self):
        if self.process is None:
            # 创建用于显示的批处理文件
            with open("message_queue_window.bat", "w", encoding="utf-8") as f:
                f.write('@echo off\n')
                f.write('chcp 65001\n')  # 设置UTF-8编码
                f.write('title Message Queue Visualizer\n')
                f.write('echo Waiting for message queue updates...\n')
                f.write(':loop\n')
                f.write('if exist "queue_update.txt" (\n')
                f.write('    type "queue_update.txt" > "message_queue_content.txt"\n')
                f.write('    del "queue_update.txt"\n')
                f.write('    cls\n')
                f.write('    type "message_queue_content.txt"\n')
                f.write(')\n')
                f.write('timeout /t 1 /nobreak >nul\n')
                f.write('goto loop\n')
            
            # 清空内容文件
            with open(self.content_file, "w", encoding="utf-8") as f:
                f.write("")
            
            # 启动新窗口
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.process = subprocess.Popen(
                ['cmd', '/c', 'start', 'message_queue_window.bat'], 
                shell=True, 
                startupinfo=startupinfo
            )
            self.is_running = True
            
            # 启动处理线程
            threading.Thread(target=self._process_messages, daemon=True).start()
    
    def _process_messages(self):
        while self.is_running:
            try:
                # 获取新消息
                text = self.message_queue.get(timeout=1)
                # 写入更新文件
                with open("queue_update.txt", "w", encoding="utf-8") as f:
                    f.write(text)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"处理队列可视化内容时出错: {e}")
    
    def update_content(self, send_temp_container):
        """更新显示内容"""
        if not self.is_running:
            return
            
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        display_text = f"Message Queue Status - {current_time}\n"
        display_text += "=" * 50 + "\n\n"
        
        # 遍历所有群组的队列
        for group_id, queue in send_temp_container.temp_queues.items():
            display_text += f"\n{'='*20} 群组: {queue.group_id} {'='*20}\n"
            display_text += f"消息队列长度: {len(queue.messages)}\n"
            display_text += f"最后发送时间: {time.strftime('%H:%M:%S', time.localtime(queue.last_send_time))}\n"
            display_text += "\n消息队列内容:\n"
            
            # 显示队列中的消息
            if not queue.messages:
                display_text += "  [空队列]\n"
            else:
                for i, msg in enumerate(queue.messages):
                    msg_time = time.strftime("%H:%M:%S", time.localtime(msg.time))
                    display_text += f"\n--- 消息 {i+1} ---\n"
                    
                    if isinstance(msg, Message_Thinking):
                        display_text += f"类型: \033[1;33m思考中消息\033[0m\n"
                        display_text += f"时间: {msg_time}\n"
                        display_text += f"消息ID: {msg.message_id}\n"
                        display_text += f"群组: {msg.group_id}\n"
                        display_text += f"用户: {msg.user_nickname}({msg.user_id})\n"
                        display_text += f"内容: {msg.thinking_text}\n"
                        display_text += f"思考时间: {int(msg.thinking_time)}秒\n"
                    else:
                        display_text += f"类型: 普通消息\n"
                        display_text += f"时间: {msg_time}\n"
                        display_text += f"消息ID: {msg.message_id}\n"
                        display_text += f"群组: {msg.group_id}\n"
                        display_text += f"用户: {msg.user_nickname}({msg.user_id})\n"
                        if hasattr(msg, 'is_emoji') and msg.is_emoji:
                            display_text += f"内容: [表情包消息]\n"
                        else:
                            # 显示原始消息和处理后的消息
                            display_text += f"原始内容: {msg.raw_message[:50]}...\n"
                            display_text += f"处理后内容: {msg.processed_plain_text[:50]}...\n"
                        
                        if msg.reply_message:
                            display_text += f"回复消息: {str(msg.reply_message)[:50]}...\n"
                            
            display_text += f"\n{'-' * 50}\n"
            
        # 添加统计信息
        display_text += "\n总体统计:\n"
        display_text += f"活跃群组数: {len(send_temp_container.temp_queues)}\n"
        total_messages = sum(len(q.messages) for q in send_temp_container.temp_queues.values())
        display_text += f"总消息数: {total_messages}\n"
        thinking_messages = sum(
            sum(1 for msg in q.messages if isinstance(msg, Message_Thinking))
            for q in send_temp_container.temp_queues.values()
        )
        display_text += f"思考中消息数: {thinking_messages}\n"
        
        self.message_queue.put(display_text)
    
    def stop(self):
        self.is_running = False
        if self.process:
            self.process.terminate()
            self.process = None
        # 清理文件
        for file in ["message_queue_window.bat", "message_queue_content.txt", "queue_update.txt"]:
            if os.path.exists(file):
                os.remove(file)

# 创建全局单例
message_visualizer = MessageVisualizer() 
