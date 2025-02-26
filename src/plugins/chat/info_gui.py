import gradio as gr
import time
import threading
from typing import Dict, List
from .message import Message

class MessageWindow:
    def __init__(self):
        self.interface = None
        self._running = False
        self.messages_history = []
        
    def _create_window(self):
        """创建Gradio界面"""
        with gr.Blocks(title="实时消息监控") as self.interface:
            with gr.Row():
                with gr.Column():
                    self.message_box = gr.Dataframe(
                        headers=["时间", "群号", "发送者", "消息内容"],
                        datatype=["str", "str", "str", "str"],
                        row_count=20,
                        col_count=(4, "fixed"),
                        interactive=False,
                        wrap=True
                    )
                    
            # 每1秒自动刷新
            self.interface.load(self._update_display, None, [self.message_box], every=1)
            
        # 启动界面
        self.interface.queue()
        self._running = True
        self.interface.launch(share=False, server_port=7860)
        
    def _update_display(self):
        """更新消息显示"""
        display_data = []
        for msg in self.messages_history[-1000:]:  # 只显示最近1000条消息
            time_str = time.strftime("%H:%M:%S", time.localtime(msg["time"]))
            display_data.append([
                time_str,
                str(msg["group_id"]),
                f"{msg['user_nickname']}({msg['user_id']})",
                msg["plain_text"]
            ])
        return display_data
            
    def update_messages(self, group_id: int, messages: List[Message]):
        """接收新消息更新"""
        for msg in messages:
            self.messages_history.append({
                "time": msg.time,
                "group_id": group_id,
                "user_id": msg.user_id,
                "user_nickname": msg.user_nickname,
                "plain_text": msg.plain_text
            })
        
        # 保持最多存储1000条消息
        if len(self.messages_history) > 1000:
            self.messages_history = self.messages_history[-1000:]
        
    def start(self):
        """启动窗口"""
        # 在新线程中启动窗口
        threading.Thread(target=self._create_window, daemon=True).start()
        
    def stop(self):
        """停止窗口"""
        self._running = False
        if self.interface:
            self.interface.close()

# 创建全局实例
message_window = MessageWindow()

