# 项目移交文档 · AI 电商视觉合规巡检系统（淘宝巡检工具）

> 生成时间：2026-08-20
> 系统性质：FastAPI + SQLite + 单页应用（SPA）全栈单体应用
> 当前代码位置（仅本地，无远程仓库）：`C:\Users\J\WorkBuddy\2026-08-17-08-58-49\app\`
> 运行环境：Windows，Python 3.13（托管虚拟环境），Edge/Playwright 浏览器内核

---

## 一、整体进度概览

| 模块 | 完成度 | 状态 |
|------|--------|------|
| 店铺管理（增删改查） | 100% | 已完成 |
| 视觉标准库（标准图录入/编辑） | 100% | 已完成 |
| 巡检任务（单链接巡检） | 100% | 已完成 |
| 巡检任务（Excel 批量导入） | 100% | 已完成 |
| 图片自动抓取（Playwright + Cookie 注入） | 85% | 进行中（代码完成，生产环境待实地验证） |
| AI 视觉比对（SSIM / pHash 算法） | 100% | 已完成 |
| 违规看板（问题列表展示） | 100% | 已完成 |
| 左右对比视图（官旗 vs 代理） | 100% | 已完成 |
| 状态流转（待处理→已通知→已修改） | 90% | 已完成（**实际为三态**，详见下） |
| 核销操作（上传截图凭证） | 60% | 部分完成（见"进行中"说明） |
| 数据报表 | 0% | 未开始 |

> **关于"已核销"**：早期设计含 `待处理→已通知→已修改→已核销` 四态，但代码已通过数据库迁移把 `verified` 并入 `modified`（见 `db.py` 第 126 行）。当前状态机为 **待处理(pending) → 已通知(notified) → 已修改(modified)** 三态，"已修改"即闭环终态。

---

## 二、当前进度详情

### 1. 已完成部分

**已实现功能清单**
- 店铺管理：增删改查 + 店铺主图上传存盘（`shops` 表，`/api/shops` 系列）。
- 视觉标准库：标准图录入/编辑 + 基准图上传 + 颜色/Logo 区域/禁用字体等字段（`standards` 表）。
- SKU 映射：官旗 SKU ↔ 代理 SKU 对照表（`sku` 表）。
- 单链接巡检：输入"代理商链接 + 官旗标准链接 + 图片类型"，后端真实抓取三类图并比对（`inspections` 表 + `/api/inspections`）。
- Excel 批量导入：下载模板 → 上传 Excel → 自动为每行建巡检并排队抓取；单次上限 1000 行（`/api/inspections/import`、`/api/template`）。
- 图片自动抓取：Playwright 真实渲染页面，按"主图 / SKU 缩略图 / 详情页长图"三类分库落盘；优先复用本机 Edge 内核，回退 Playwright 自带 Chromium；反爬拦截时回退浏览器元素截图。
- AI 视觉比对：`compare.py` 实现 **SSIM（逐通道 RGB 平均）+ 感知哈希 pHash + 汉明距离 + 差异区域 diff_region**，主图集合最优匹配、SKU 最佳相似对齐、详情图 pHash 集合匹配。
- 违规看板：问题卡片、状态筛选（待处理/已通知/已修改）、分组折叠、新增/重抓/上传复核/批量通知。
- 左右对比视图：`renderCompare()` 渲染官旗(左) vs 代理(右) 三类对比区，差异区域红框标注（`diff_bbox`）。
- 批量通知：按邮件模板生成整改通知文案，并把状态置为 `notified`（模板真实存库）。
- 本地登录唤醒（扫码免 Cookie）：Playwright 开有头浏览器 → 手机淘宝扫码 → 检测登录态 → 保存 `auth.json` 供后续抓取复用；含"取消/清除/重扫"与诊断字段。
- 多人实时协作（SSE）：在线状态、协作动态时间线、操作归属日志（`members` + `activity_log` + `/api/events`）。
- 项目设置：视觉阈值、价格容差、邮件模板，落库 `settings` / `email_template`。

**可演示 Demo / 测试环境**
- 当前在你本机运行：`http://127.0.0.1:8000`（已验证在线，且已存有真实的淘宝登录态 Cookie：`tracknick`、`sgcookie`）。
- ⚠️ 该地址**仅本机/局域网可访问**，不是公开部署。若要给新同事演示，需在同一台机器或内网访问。
- 接口自文档：FastAPI 自带 Swagger，访问 `http://127.0.0.1:8000/docs`（OpenAPI JSON 在 `/openapi.json`）。

**代码是否提交仓库**
- ✅ **已初始化本地 Git 仓库**（分支 `master`，基线提交 `f99aeaa`，含 16 个文件：全部源码 + 文档；已排除 `auth.json`、运行时 DB、`uploads/` 用户上传、`.workbuddy/` 内部数据）。
- ⏳ **尚未推送远程**：请提供内网 Git 地址（GitLab/GitHub），执行 `git remote add origin <url> && git push -u origin master` 即可。详见"六、后续计划"。

### 2. 进行中部分

- **图片抓取生产环境实地验证**：抓取逻辑已写完，但本沙箱无外网，无法端到端验证真实淘宝页面的抓取质量（主图轮播、详情 iframe、SKU 色卡）。需在有网机器上跑真实巡检确认召回率。
- **核销闭环补全（当前 60%）**：现有"上传复核图"（`/api/inspections/{id}/recheck`）可上传整改图并重新比对，但它只是"再比对"，**没有独立的"已核销"状态、没有凭证截图存档、不记录谁在何时核销**。若业务要求留痕，需补一个 `verified` 状态 + 凭证图字段。
- **数据报表（0%）**：目前只有仪表盘几个计数卡（待处理/已修改数量），**没有**导出 CSV/Excel、按店铺/时间维度的统计图表、违规趋势等功能。

### 3. 遇到的技术难题（阻塞 / 需协助）

| 问题 | 描述 | 尝试过的方案 | 需要贵方协助 |
|------|------|--------------|--------------|
| 🟢 无版本控制（已解决） | 已初始化本地 Git 仓库（分支 `master`，基线提交 `f99aeaa`）。**待推送内网 Git 远程**（见"六、后续计划"） | 已 `git init` + 提交基线 + `.gitignore` 排除密钥/运行时数据 | 请提供内网 Git 地址，执行 `git remote add origin <url> && git push -u origin master` |
| 🟢 `requirements.txt` 不完整（已解决） | 已补全 `playwright`、`openpyxl`、`requests`，并将全部依赖对齐到验证环境实际安装版本（`app/requirements.txt`） | 已写入并校验；`pip install -r requirements.txt` 后应用可正常启动 | 若贵方私有索引版本号不同，`pip install` 报 "version not found" 时按索引可用版本微调即可 |
| 🟡 淘宝反爬（滑块/验证/限流） | 登录墙已能识别并提示填 Cookie；但出现**滑块验证(#slide-code/.nc-container)、IP 限流**时，抓取会失败并降级为演示图，需要人重新扫码 | 加了登录态 Cookie 注入、扫码唤醒、登录墙检测、recrawl 重抓 | 若需自动过滑块，需引入打码/人工验证服务（超出当前架构）；目前靠"过期→重扫"兜底 |
| 🟡 单实例限制 | SSE 实时协作基于进程内事件总线，**多实例部署会导致协作者互不可见** | DEPLOY.md 已写明"单实例部署" | 上线时务必**关闭自动横向扩容**，挂载持久卷到 `DATA_DIR` |
| 🟢 数据持久化 | SQLite 在临时文件系统（Railway/Render）重启会丢数据 | 已支持 `DATA_DIR` 环境变量 + WAL | 上线挂载持久磁盘并设 `DATA_DIR` |

---

## 三、关于图片抓取（核心难点）

之前确认的方案是「Cookie 注入 + 手动上传兜底」，进度如下：

- ☑ **Cookie 管理后台是否已开发完成？**
  是。两套机制并存：
  1. **扫码免 Cookie（推荐）**："本地登录唤醒"——手机淘宝扫码 → 存 `auth.json` → 后续抓取自动加载。
  2. **单条 Cookie 粘贴框**：单链接巡检表单有"淘宝/天猫登录态 Cookie"输入框，可贴 `k=v;k2=v2`。
  抓取时优先用 `auth.json`，无则用该条粘贴的 Cookie。

- ☑ **Playwright 抓取脚本是否已调通（能否成功抓到淘宝商品图）？**
  代码层面已完成且功能闭环（主图轮播、SKU 色卡、详情 iframe 三类分抓 + 高清化 + 反爬回退截图）。
  **验证情况**：你本机已成功扫码拿到真实登录态，但真实淘宝页面的端到端抓取质量（召回率/误判率）尚未在联网环境下完整回归——沙箱无网，只能用合成图验证逻辑通路。建议新同事接手后，用 3~5 个真实商品链接跑一轮，确认主图/SKU/详情抓取准确。

- ☑ **抓取失败时降级为「待人工补图」的逻辑是否已实现？**
  是。`crawler.py` 命中登录墙会标记 `login_wall`，巡检记录提示"需填 Cookie 后点重新抓取"；真实抓取一张图都没拿到时降级为演示图并明确标注"哪条链接未真实抓取"；前端提供"重新抓取复核(recalc)"与"上传复核图(recheck)"两个人工补图入口。

- ☐ **是否踩到了新的反爬坑（滑块验证、IP 限流等）？**
  已踩到"**登录墙**"这一层（已处理：提示填 Cookie + 重扫）。
  **滑块/验证码、IP 限流尚未自动处理**：一旦淘宝弹出滑块或限流，本次抓取会失败降级。当前对策是"登录态过期/被风控 → 重新扫码"，属于人工兜底，不是自动突破。

---

## 四、代码与文档

- **代码仓库地址**：无。本地路径 `C:\Users\J\WorkBuddy\2026-08-17-08-58-49\app\`。**请尽快建立 Git 仓库并推送**。
- **README / 部署文档**：有 `app/DEPLOY.md`（覆盖目录结构、环境变量、Docker/Railway/Render 三种部署、并发抓取限制、实时协作单实例注意、启用联网抓取步骤）。根目录无独立 README。
- **数据库表结构 / ER 说明**：
  - 无图形 ER 图，但结构清晰。核心表（均在 `db.py` 定义）：
    - `shops`（店铺）、`sku`（SKU 映射）、`standards`（视觉标准库）
    - `inspections`（巡检主表：agent_url/official_url/image_type/state/status/三类图文件名/三类比对结果/价格/error/cookies）
    - `members`（成员登记）、`activity_log`（协作动态）
    - `settings`、`email_template`（阈值/模板）
    - `tasks`、`issues`、`targets` 为**早期遗留表，新逻辑已不再使用**，可忽略或后续清理。
  - 关系：`inspections` 独立存对照链接；`shops`/`standards`/`sku` 为可复用的基础数据，与 `inspections` 通过 URL/名称松散关联（非外键强约束）。
- **接口文档**：无独立手写文档。运行时访问 `http://127.0.0.1:8000/docs` 即为完整 Swagger 接口文档（由 FastAPI 自动生成），`/openapi.json` 可导出。

---

## 五、后续计划

- **下一阶段开发计划**
  1. （建议优先）补 `requirements.txt` 缺失依赖，建立 Git 仓库 + CI 基本检查。
  2. 在联网环境实测淘宝真实抓取，调优选择器与阈值（主图轮播、详情 iframe、SKU 色卡）。
  3. 按需补全"核销"闭环（状态 + 凭证截图 + 操作留痕）。
  4. 按需开发"数据报表"（导出、按店铺/时间统计、违规趋势）。
  5. 若需规模化，评估把 SQLite 换 PostgreSQL（`db.py` 连接层可平滑替换，接口不变）。

- **MVP 交付时间预估**
  - 以"单链接巡检 + 真实抓取 + AI 比对 + 违规看板 + 左右对比 + 扫码登录"为 MVP 范围，**当前已具备可用 MVP 能力**，缺的是**联网实地验证**和**版本控制/部署规范化**。
  - 若新同事 1 人接手、每天可投入：补依赖+建仓（0.5 天）、联网回归测试与调优（2~3 天）、核销/报表按需（各 2~3 天）。MVP 稳定版约 **1~2 周**可达。

- **新同事需提前熟悉的技术栈**
  - Python 3.11+（建议 3.13 一致）
  - FastAPI / Uvicorn（后端 + SSE）
  - Playwright（Python 版，浏览器自动化/抓取）
  - 图像处理：Pillow、NumPy、OpenCV 思路（实际用 NumPy 自实现 SSIM/pHash，未直接依赖 OpenCV）
  - 前端：原生 HTML/JS SPA（Fetch + EventSource/SSE），无框架、无构建步骤
  - SQLite（WAL 模式）、openpyxl（Excel 导入/模板）
  - 部署：Docker / Railway / Render 任选其一，`DATA_DIR` 持久化

---

## 六、交接需要的材料

### 1. 项目目录结构说明

```
2026-08-17-08-58-49/
├── app/                         # 后端 + 前端单体目录
│   ├── app.py                  # FastAPI 主程序：全部 API 路由、SSE、巡检队列、扫码登录
│   ├── db.py                   # SQLite 持久层（建表、CRUD、WAL）
│   ├── crawler.py              # Playwright 分类抓取（主图/SKU/详情三库分存）+ 登录态判定
│   ├── compare.py              # 图像比对（SSIM/pHash/diff_region/主图·SKU·详情比对）
│   ├── index.html              # 前端 SPA（店铺/标准库/巡检看板/对比/设置/成员）
│   ├── launcher.py             # Windows 常驻启动器（端口掉了自动重启 app.py，单实例锁）
│   ├── start_server.bat        # 无窗口启动 launcher（pythonw）
│   ├── requirements.txt        # ✅ 已补全 playwright/openpyxl/requests（对齐验证环境版本）
│   ├── Dockerfile / Procfile   # 容器/平台部署
│   ├── DEPLOY.md               # 部署指南
│   ├── uploads/                # 运行时生成的图片（主图/SKU/详情/复核/种子）
│   ├── app.db / app.db-wal/-shm# SQLite 数据文件
│   └── auth.json              # 扫码登录态（淘宝 Cookie，请勿提交进仓库）
└── fix_scan_login_20260820.md  # 上次"扫码登录卡住"的修复记录
```

### 2. 环境依赖清单

**`requirements.txt`（已补全，对齐验证环境实际安装版本）**
```
fastapi==0.141.1
uvicorn[standard]==0.52.3
pillow==12.3.0
numpy==2.5.2
python-multipart==0.0.32
gunicorn==23.0.0
requests==2.34.2        # crawler.py 真实图片字节下载
playwright==1.62.0      # crawler.py 顶层 import，缺失会导致 app 启动失败
openpyxl==3.1.5         # Excel 导入/模板导出
```
> 若 `pip install` 报某版本 "could not find version"，说明贵方索引与开发机不同，按可用版本微调即可（这些版本是开发机实测可运行的基线）。
> 浏览器内核安装（任选其一）：复用本机 Edge 无需额外安装；或 `pip install playwright && playwright install chromium`。

### 3. 本地运行步骤（从零到启动）

```bash
# 1) 准备 Python 3.13（或 3.11+）
# 2) 创建并激活虚拟环境
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3) 安装依赖（requirements.txt 已含全部依赖，一次性安装即可）
pip install -r app/requirements.txt
playwright install chromium      # 若无本机 Edge 才需要（可用本机 Edge 替代）

# 4) 进入 app 目录启动
cd app
python app.py                   # 监听 0.0.0.0:8000

# 5) 浏览器打开 http://localhost:8000
#    首次进入需填写"真实姓名 + 部门"登记为成员
```

**常驻（开机/崩溃自启，可选）**
```bat
:: start_server.bat（已存在，双击即用，无窗口）
cd /d "C:\...\app"
start "" pythonw.exe launcher.py
```

### 4. 配置文件说明（环境变量）

| 变量 | 默认值 | 含义 |
|------|--------|------|
| `HOST` | `0.0.0.0` | 监听地址（容器内用 0.0.0.0 才外网可达） |
| `PORT` | `8000` | 监听端口 |
| `DATA_DIR` | 应用目录 | 持久化目录（SQLite + uploads）。**上线务必挂载持久卷到此变量**，否则重启丢数据 |

> 无 `.env` 文件，全部走环境变量；无密钥/密钥类配置（淘宝登录态存于 `auth.json`，属用户隐私，**切勿提交进 Git**）。

### 5. 测试账号 / 测试数据

- **无固定测试账号**：系统采用"首次进入登记"机制——打开页面后填写真实姓名 + 部门即注册为成员（`members` 表），无密码、无登录态隔离。
- **内置种子数据**（`seed_if_empty()` 自动生成，仅当 shops 为空时）：1 个官旗店、2 个代理店、1 条视觉标准，用于直接演示比对。
- **测试用商品链接**：需自行准备真实淘宝/天猫商品 URL（沙箱无网，仅在你的联网机器上能跑真实抓取）。
- **演示图兜底**：无外网时系统自动生成确定性合成图（标注 `simulated=True`），保证比对引擎链路可演示，但**不是真实商品图**。

---

## 七、移交前必须处理的事项（清单）

1. ✅ **建立 Git 仓库**：已完成本地 `git init`，基线提交 `f99aeaa`（分支 `master`，16 文件，已排除 `auth.json`/运行时 DB/`uploads`/`.workbuddy`）。**待推送**：`git remote add origin <内网Git地址> && git push -u origin master`。
2. ✅ **补全 `requirements.txt`**：已加 playwright / openpyxl / requests，并对齐验证环境版本，避免新环境启动即崩。
3. ✅ `auth.json` 与运行时数据已纳入 `.gitignore`（含登录态 Cookie，隐私保护）。
4. 🟡 在联网机器上跑 3~5 个真实链接，回归抓取质量。
5. 🟢 视业务需要补"核销留痕"与"数据报表"。

---

_本文件由 WorkBuddy 在 2026-08-20 依据 `app.py / crawler.py / compare.py / db.py / index.html / DEPLOY.md` 等源码实地核查生成，反映当时真实代码状态。_
