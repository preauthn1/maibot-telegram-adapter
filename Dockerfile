FROM python:3.13.7-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 工作目录
WORKDIR /MaiMBot

# 复制依赖列表
COPY requirements.txt .
# 同级目录下需要有 MaiMBot-LPMM
COPY MaiMBot-LPMM /MaiMBot-LPMM

# 编译器
RUN apt-get update && apt-get install -y build-essential
RUN uv pip install --system --upgrade pip

# lpmm编译安装
RUN cd /MaiMBot-LPMM && uv pip install --system -r requirements.txt
RUN uv pip install --system Cython py-cpuinfo setuptools
RUN cd /MaiMBot-LPMM/lib/quick_algo && python build_lib.py --cleanup --cythonize --install


# 安装依赖
RUN uv pip install --system -r requirements.txt

# 复制项目代码
COPY . .

EXPOSE 8000

ENTRYPOINT [ "python","bot.py" ]
