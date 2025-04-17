import tkinter as tk
from tkinter import ttk
import time
import os
from datetime import datetime
import random
from collections import deque
import json # 引入 json

# --- 引入 Matplotlib ---
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates # 用于处理日期格式
import matplotlib # 导入 matplotlib

# --- 配置 ---
LOG_FILE_PATH = os.path.join("logs", "interest", "interest_history.log") # 指向历史日志文件
REFRESH_INTERVAL_MS = 200 # 刷新间隔 (毫秒) - 可以适当调长，因为读取文件可能耗时
WINDOW_TITLE = "Interest Monitor (Live History)"
MAX_HISTORY_POINTS = 1000 # 图表上显示的最大历史点数 (可以增加)
MAX_STREAMS_TO_DISPLAY = 15 # 最多显示多少个聊天流的折线图 (可以增加)

# *** 添加 Matplotlib 中文字体配置 ***
# 尝试使用 'SimHei' 或 'Microsoft YaHei'，如果找不到，matplotlib 会回退到默认字体
# 确保你的系统上安装了这些字体
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
matplotlib.rcParams['axes.unicode_minus'] = False # 解决负号'-'显示为方块的问题

class InterestMonitorApp:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry("1800x800") # 调整窗口大小以适应图表

        # --- 数据存储 ---
        # 使用 deque 来存储有限的历史数据点
        # key: stream_id, value: deque([(timestamp, interest_level), ...])
        self.stream_history = {}
        self.stream_colors = {} # 为每个 stream 分配颜色
        self.stream_display_names = {} # *** New: Store display names (group_name) ***

        # --- UI 元素 ---
        # 状态标签
        self.status_label = tk.Label(root, text="Initializing...", anchor="w", fg="grey")
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=2)

        # Matplotlib 图表设置
        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        # 配置在 update_plot 中进行，避免重复

        # 创建 Tkinter 画布嵌入 Matplotlib 图表
        self.canvas = FigureCanvasTkAgg(self.fig, master=root)
        self.canvas_widget = self.canvas.get_tk_widget()
        self.canvas_widget.pack(side=tk.TOP, fill=tk.BOTH, expand=1)

        # --- 初始化和启动刷新 ---
        self.update_display() # 首次加载并开始刷新循环

    def get_random_color(self):
        """生成随机颜色用于区分线条"""
        return "#{:06x}".format(random.randint(0, 0xFFFFFF))

    def load_and_update_history(self):
        """从 history log 文件加载数据并更新历史记录"""
        if not os.path.exists(LOG_FILE_PATH):
            self.set_status(f"Error: Log file not found at {LOG_FILE_PATH}", "red")
            # 如果文件不存在，不清空现有数据，以便显示最后一次成功读取的状态
            return

        # *** Reset display names each time we reload ***
        new_stream_history = {}
        new_stream_display_names = {}
        read_count = 0
        error_count = 0
        # *** Calculate the timestamp threshold for the last 30 minutes ***
        current_time = time.time()
        time_threshold = current_time - (15 * 60) # 30 minutes in seconds

        try:
            with open(LOG_FILE_PATH, 'r', encoding='utf-8') as f:
                for line in f:
                    read_count += 1
                    try:
                        log_entry = json.loads(line.strip())
                        timestamp = log_entry.get("timestamp")

                        # *** Add time filtering ***
                        if timestamp is None or float(timestamp) < time_threshold:
                            continue # Skip old or invalid entries

                        stream_id = log_entry.get("stream_id")
                        interest_level = log_entry.get("interest_level")
                        group_name = log_entry.get("group_name", stream_id) # *** Get group_name, fallback to stream_id ***

                        # *** Check other required fields AFTER time filtering ***
                        if stream_id is None or interest_level is None:
                             error_count += 1
                             continue # 跳过无效行

                        # 如果是第一次读到这个 stream_id，则创建 deque
                        if stream_id not in new_stream_history:
                            new_stream_history[stream_id] = deque(maxlen=MAX_HISTORY_POINTS)
                            # 检查是否已有颜色，没有则分配
                            if stream_id not in self.stream_colors:
                                self.stream_colors[stream_id] = self.get_random_color()
                        
                        # *** Store the latest display name found for this stream_id ***
                        new_stream_display_names[stream_id] = group_name 

                        # 添加数据点
                        new_stream_history[stream_id].append((float(timestamp), float(interest_level)))

                    except json.JSONDecodeError:
                        error_count += 1
                        # logger.warning(f"Skipping invalid JSON line: {line.strip()}")
                        continue # 跳过无法解析的行
                    except (TypeError, ValueError) as e:
                         error_count += 1
                         # logger.warning(f"Skipping line due to data type error ({e}): {line.strip()}")
                         continue # 跳过数据类型错误的行

            # 读取完成后，用新数据替换旧数据
            self.stream_history = new_stream_history
            self.stream_display_names = new_stream_display_names # *** Update display names ***
            status_msg = f"Data loaded at {datetime.now().strftime('%H:%M:%S')}. Lines read: {read_count}."
            if error_count > 0:
                 status_msg += f" Skipped {error_count} invalid lines."
                 self.set_status(status_msg, "orange")
            else:
                 self.set_status(status_msg, "green")

        except IOError as e:
            self.set_status(f"Error reading file {LOG_FILE_PATH}: {e}", "red")
        except Exception as e:
            self.set_status(f"An unexpected error occurred during loading: {e}", "red")


    def update_plot(self):
        """更新 Matplotlib 图表"""
        self.ax.clear() # 清除旧图
        # *** 设置中文标题和标签 ***
        self.ax.set_title("兴趣度随时间变化图")
        self.ax.set_xlabel("时间")
        self.ax.set_ylabel("兴趣度")
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        self.ax.grid(True)
        self.ax.set_ylim(0, 10) # 固定 Y 轴范围 0-10

        # 只绘制最新的 N 个 stream (按最后记录的兴趣度排序)
        # 注意：现在是基于文件读取的快照排序，可能不是实时最新
        active_streams = sorted(
            self.stream_history.items(),
            key=lambda item: item[1][-1][1] if item[1] else 0, # 按最后兴趣度排序
            reverse=True
        )[:MAX_STREAMS_TO_DISPLAY]

        all_times = [] # 用于确定 X 轴范围

        for stream_id, history in active_streams:
            if not history:
                continue

            timestamps, interests = zip(*history)
            # 将 time.time() 时间戳转换为 matplotlib 可识别的日期格式
            try:
                mpl_dates = [datetime.fromtimestamp(ts) for ts in timestamps]
                all_times.extend(mpl_dates) # 收集所有时间点
                
                # *** Use display name for label ***
                display_label = self.stream_display_names.get(stream_id, stream_id)

                self.ax.plot(
                    mpl_dates,
                    interests,
                    label=display_label, # *** Use display_label ***
                    color=self.stream_colors.get(stream_id, 'grey'), 
                    marker='.',
                    markersize=3, 
                    linestyle='-',
                    linewidth=1 
                )
            except ValueError as e:
                 print(f"Skipping plot for {stream_id} due to invalid timestamp: {e}")
                 continue

        if all_times:
             # 根据数据动态调整 X 轴范围，留一点边距
             min_time = min(all_times)
             max_time = max(all_times)
             # delta = max_time - min_time
             # self.ax.set_xlim(min_time - delta * 0.05, max_time + delta * 0.05)
             self.ax.set_xlim(min_time, max_time)

             # 自动格式化X轴标签
             self.fig.autofmt_xdate()
        else:
            # 如果没有数据，设置一个默认的时间范围，例如最近一小时
            now = datetime.now()
            one_hour_ago = now - timedelta(hours=1)
            self.ax.set_xlim(one_hour_ago, now)


        # 添加图例
        if active_streams:
             # 调整图例位置和大小
             # 字体已通过全局 matplotlib.rcParams 设置
             self.ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), borderaxespad=0., fontsize='x-small')
             # 调整布局，确保图例不被裁剪
             self.fig.tight_layout(rect=[0, 0, 0.85, 1]) # 右侧留出空间给图例


        self.canvas.draw() # 重绘画布

    def update_display(self):
        """主更新循环"""
        try:
            self.load_and_update_history() # 从文件加载数据并更新内部状态
            self.update_plot()             # 根据内部状态更新图表
        except Exception as e:
            # 提供更详细的错误信息
            import traceback
            error_msg = f"Error during update: {e}\n{traceback.format_exc()}"
            self.set_status(error_msg, "red")
            print(error_msg) # 打印详细错误到控制台

        # 安排下一次刷新
        self.root.after(REFRESH_INTERVAL_MS, self.update_display)

    def set_status(self, message: str, color: str = "grey"):
        """更新状态栏标签"""
        # 限制状态栏消息长度
        max_len = 150
        display_message = (message[:max_len] + '...') if len(message) > max_len else message
        self.status_label.config(text=display_message, fg=color)


if __name__ == "__main__":
    # 导入 timedelta 用于默认时间范围
    from datetime import timedelta
    root = tk.Tk()
    app = InterestMonitorApp(root)
    root.mainloop() 