# syntax=docker/dockerfile:1.9
# 基础镜像走 DaoCloud Docker Hub 代理；Python 包装阿里云 PyPI
FROM docker.m.daocloud.io/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_DEFAULT_INDEX=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    MEMORY_API_HOST=0.0.0.0 \
    MEMORY_API_PORT=8000

RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ uv

WORKDIR /app

COPY . .

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --extra locomo --no-dev \
    --default-index https://mirrors.aliyun.com/pypi/simple/

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "python", "examples/locomo/main_server.py"]
