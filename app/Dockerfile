# AI电商视觉合规巡检系统 — 生产部署镜像
FROM python:3.13-slim

WORKDIR /app

# 系统依赖：启用真实 Playwright 抓取淘宝/天猫商品图所需浏览器内核
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 fonts-liberation \
    socat \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# 安装 Chromium 内核（Playwright 抓取依赖）
RUN playwright install chromium

COPY . .

# 数据持久化：请将宿主机的持久目录挂载到 /app/data，并设环境变量 DATA_DIR=/app/data
ENV HOST=0.0.0.0 PORT=8000 DATA_DIR=/app/data
EXPOSE 8000

# 生产用 gunicorn + uvicorn worker，比单进程 uvicorn 更稳、可扛并发
CMD ["sh", "-c", "mkdir -p ${DATA_DIR:-/app/data}; P=${PORT:-8000}; if [ \"$P\" != \"8000\" ]; then echo \"[boot] socat: $P -> 8000\"; socat TCP-LISTEN:$P,fork,reuseaddr TCP:127.0.0.1:8000 & fi; exec gunicorn app:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --workers 1"]
