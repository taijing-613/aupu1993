# AI电商视觉合规巡检系统 — 生产部署镜像
FROM python:3.13-slim

WORKDIR /app

# 系统依赖（如需启用真实 Playwright 抓取，请取消下一行注释并放开 crawler.py 中的 playwright 依赖）
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
#     libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
#     libgbm1 libasound2 libpango-1.0-0 libcairo2 fonts-liberation && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 数据持久化：请将宿主机的持久目录挂载到 /app/data，并设环境变量 DATA_DIR=/app/data
ENV HOST=0.0.0.0 PORT=8000 DATA_DIR=/app/data
EXPOSE 8000

CMD ["sh", "-c", "mkdir -p ${DATA_DIR:-.} && exec uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
