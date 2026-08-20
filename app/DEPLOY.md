# 部署指南（AI电商视觉合规巡检系统）

本目录是一个 **FastAPI + SQLite 全栈应用**，需要能运行 Python 的托管环境（CloudStudio 等纯静态托管**无法**运行后端，请勿直接上传整个目录到静态空间）。

## 目录结构
```
app/
├── app.py          # FastAPI 后端：精准对照表单链接巡检 / 分类抓取 / 组对比 / Excel模板·导入 / 成员登记 / 实时协作(SSE)
├── db.py           # SQLite 持久层（WAL 并发；shops/sku/standards/tasks/members/settings/activity_log/inspections）
├── compare.py      # 真实图像比对（SSIM + 感知哈希）+ diff_region + compare_pair/sku/detail
├── crawler.py      # 分类抓取 crawl_product()：主图/SKU数组/详情数组 三库分存（无网时确定性降级）
├── index.html      # Linear 风格可编辑 SPA（前后端同进程，/ 直接返回此文件，内置实时协作）
├── requirements.txt
├── Dockerfile
├── Procfile
└── uploads/        # 真实存储的基准图与违规截图（运行时生成）
```

## 环境变量
| 变量 | 说明 | 默认 |
|------|------|------|
| `HOST` | 监听地址 | `0.0.0.0` |
| `PORT` | 监听端口 | `8000` |
| `DATA_DIR` | 持久化目录（SQLite + 图片）。**重启后数据是否保留取决于它是否在持久卷上** | 应用目录 |

## 方式一：Docker（自有服务器 / 任意支持容器的平台）
```bash
cd app
docker build -t ai-audit .
# 挂载持久卷，避免容器重建丢数据
docker run -d --name ai-audit \
  -p 8000:8000 \
  -v /your/persistent/path:/app/data \
  -e DATA_DIR=/app/data \
  ai-audit
# 访问 http://<服务器IP>:8000
```

## 方式二：Railway
1. 新建 Project → Deploy from GitHub（连接本仓库的 `app/` 子目录，或单独把 `app/` 推到一个仓库）。
2. Start Command 填：`uvicorn app:app --host 0.0.0.0 --port $PORT`
3. 在 Variables 里加：`DATA_DIR=/app/data`，并在 Volumes 中挂载 `/app/data`（Railway 提供持久磁盘）。
4. 部署完成后 Railway 给出公开 URL。

## 方式三：Render
1. New → Web Service，连接仓库。
2. Build Command：`pip install -r requirements.txt`
3. Start Command：`uvicorn app:app --host 0.0.0.0 --port $PORT`
4. 在 Advanced → Add Disk 挂载 `/app/data`，并设置环境变量 `DATA_DIR=/app/data`。

## 数据持久化重要提示
- SQLite 文件写在 `DATA_DIR/app.db`，图片写在 `DATA_DIR/uploads/`。
- **Railway / Render 等临时文件系统**：容器重启/重部署会清空未挂载目录。务必挂载持久卷到 `DATA_DIR`，否则巡检数据与成员记录会丢失。
- 数据量增长后可平滑迁移到 PostgreSQL（仅替换 `db.py` 连接层即可，接口不变）。

## 启用真实联网抓取
真实抓取在**有外网**的环境中即可工作，无需额外配置即可抓到真实图片：
- **优先复用本机已装浏览器**：若系统已安装 Microsoft Edge，`crawler.py` 自动用其 Chromium 内核抓取（免下载）。
- **或安装 Playwright 自带 Chromium**：
```bash
pip install playwright
playwright install chromium
```
`crawler.py` 将自动改用 Playwright 真实访问店铺 URL，按主图/SKU/详情三类**下载真实图片字节**（被反爬拦截时回退为元素截图），比对引擎（SSIM/pHash/价格正则）无需改动。
- **兜底语义**：仅当某条链接本身不可达（导航超时 / 被反爬拦截且截图也失败）时，才会对该链接降级为确定性合成图，并在巡检记录中标注「哪条链接未能真实抓取」。正常有网环境对真实商品页可稳定抓到真实图片。
- **抓取淘宝 / 天猫需登录态 Cookie**：淘宝、天猫商品页未登录会被登录墙拦截（只能拿到登录页图）。在违规看板「单链接巡检」表单的「淘宝/天猫登录态 Cookie」框粘贴从浏览器开发者工具复制的 Cookie（`k=v; k2=v2`），即可带登录态真实抓取主图/SKU/详情。命中登录墙时记录会醒目提示需填 Cookie，点「重新抓取复核」即带 Cookie 重抓。

## 首次访问
打开站点后，系统会要求每位用户先填写**真实姓名 + 所在部门**（登记到 `members` 表），之后左侧「成员」页可见全部登记用户。其余店铺管理 / 视觉标准库 / 违规看板的操作与本地完全一致。

## 多人实时协作（已内置）
本应用支持**多人同时在线协作、彼此实时可见对方的增删改**：
- **实时同步**：任何人的新增 / 编辑 / 删除 / 整改操作，都会通过 SSE 即时推送给所有在线协作者，对应页面自动刷新，并弹出「👤 某某 更新了…」提示，无需手动刷新。
- **在线状态**：左侧边栏显示「N 人在线」及在线成员头像；「成员」页中，当前在线的成员名字旁有绿点标识。客户端每 15 秒上报一次心跳（接口 `/api/heartbeat`）。
- **团队协作动态**：仪表盘内置「团队协作动态」时间线（接口 `/api/activity`），实时滚动展示全员的每一次操作归属（谁、做了什么、何时），并落库到 `activity_log` 表，可作为审计追溯。
- **操作归属**：所有写操作都会从请求头 `X-User-Id` 解析出当前操作者并记入活动日志，便于追责。

### 协作部署注意（重要）
- **单实例要求**：实时推送（SSE）与在线状态基于进程内事件总线，**请部署为「单实例」**。Railway / Render 默认即为单实例，直接按下方方式部署即可；**不要开启多实例 / 自动横向扩容**，否则不同实例间的协作者互不可见（多实例需改用 Redis 发布订阅，本包未内置）。
- **共享数据库**：多人并发写入依赖 SQLite 的 WAL 模式（已在 `db.py` 开启 `PRAGMA journal_mode=WAL` + `busy_timeout`）。务必按下方「数据持久化」挂载 `DATA_DIR` 持久卷，否则并发写入可能锁表。
- 局域网内临时协作：本机启动后，同事用你的内网 IP 访问 `http://<你的内网IP>:8000` 即可（服务已绑定 `0.0.0.0`）。

## 并发抓取限制（重要）
每条巡检都会真实启动浏览器（官旗 + 代理共 2 个实例）抓取三类图片。**早期版本为每行直接开线程，批量导入几十行会瞬间并发拉起上百个浏览器，把本机 CPU/内存打满，连带同机运行的浏览器标签页直接卡死。**

现改为 **有界爬虫线程池**：
- 全局固定 `CRAWLER_MAX_WORKERS = 2` 个 worker，同时最多只跑 2 条巡检（即最多 4 个浏览器实例），其余任务在内存队列中排队（`queued` 状态）。
- 所有入口（单条新增 / 重新抓取 / 批量导入每行）统一走 `enqueue_inspection()` 入队，不再无限制 `threading.Thread().start()`。
- 单次导入行数上限 `CRAWLER_MAX_IMPORT_ROWS = 1000`；超出时仅导入前 1000 条并提示分批上传。
- 看板中任务会先显示「队列中」，轮到执行才变「抓取中…」，不会因瞬时并发而卡顿。

如需在性能更强的机器上提速，可调大 `app.py` 中的 `CRAWLER_MAX_WORKERS`（建议不超过 CPU 核数的一半，且每个 worker 约占用 1 个浏览器实例的内存）。
