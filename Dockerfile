FROM python:3.13.2-slim-bookworm

# 工作目录
WORKDIR /MaiMBot

# 复制依赖列表
COPY requirements.txt .
# 同级目录下需要有 maim_message
COPY maim_message /maim_message

# 安装依赖
RUN pip install -e /maim_message -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple
RUN pip install --upgrade -r requirements.txt -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple

# 复制项目代码
COPY . .

EXPOSE 8000
ENTRYPOINT [ "python","bot.py" ]