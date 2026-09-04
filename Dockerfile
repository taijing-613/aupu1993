# AI电商视觉合规巡检系统 — 生产部署镜像（仓库根目录版本）
#
# 为何放在根目录：Railway 默认在仓库根目录寻找 Dockerfile 并自动用它构建。
# 本文件把 app/ 子目录的内容复制进镜像，因此「不需要在后台填写 Root Directory」，
# 避免漏填导致 Railpack 在根目录找不到 requirements.txt 而构建失败。
FROM python:3.13-slim

WORKDIR /app

# 系统依赖：启用真实 Playwright 抓取淘宝/天猫商品图所需浏览器内核
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 fonts-liberation \
    socat \
    && rm -rf /var/lib/apt/lists/*

# 依赖文件在 app/ 下，先单独复制以利用 Docker 缓存层
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安装 Chromium 内核（Playwright 抓取依赖）
RUN playwright install chromium

# 复制应用源码
COPY app/ .

# 数据持久化：请将宿主机的持久目录挂载到 /app/data，并设环境变量 DATA_DIR=/app/data
ENV HOST=0.0.0.0 PORT=8000 DATA_DIR=/app/data
EXPOSE 8000

# 生产用 gunicorn + uvicorn worker，比单进程 uvicorn 更稳、可扛并发
#
# 端口兼容说明（解决 Railway 502 "Application failed to respond"）：
# 云平台会注入 PORT 环境变量，但对外域名转发的目标端口可能是 8000（来自 EXPOSE），
# 两者不一致就会出现「服务显示在线、访问却是 502」。
# 这里做双重兜底：
#   1. 应用固定监听 8000；
#   2. 若平台注入的 PORT 不是 8000，额外起一个 socat 把该端口转发到 8000。
# 这样无论外部访问的是 $PORT 还是 8000，都能正常响应。
CMD ["sh", "-c", "mkdir -p ${DATA_DIR:-/app/data}; P=${PORT:-8000}; if [ \"$P\" != \"8000\" ]; then echo \"[boot] socat: $P -> 8000\"; socat TCP-LISTEN:$P,fork,reuseaddr TCP:127.0.0.1:8000 & fi; exec gunicorn app:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --workers 1"]
