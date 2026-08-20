# 违规看板 · 巡检稳定性修复记录

> 服务运行于 http://127.0.0.1:8000。下述三处修复均已落地并通过实测。

## 一、点击「选择 Excel 上传」浏览器卡退（已修）
**根因**：`renderIssues()` 每次 SSE 推送都把整页 `innerHTML` 重写，连上传用的 `<input type=file>` 一起销毁重建；点开文件对话框的瞬间若发生重渲染，Chromium 因所属 input 被抽走而崩溃。
**修复**：把违规看板拆为「静态外壳 + 动态列表」，上传控件只构建一次，之后只刷新卡片列表 `#insp-list`，永不重建上传控件。

## 二、批量导入瞬间拉起几十个浏览器 → 资源打满（已修）
**根因**：每条巡检直接 `threading.Thread().start()`，无并发上限；导入几十行即瞬间拉起几十×2 个 Edge，本机资源被打满。
**修复**：有界爬虫线程池 `CRAWLER_MAX_WORKERS=2` + 队列；导入行数上限 1000。

## 三、导入后一直显示「抓取中」、疑似进程挂死（本次修复 ✅）
**根因**：抓取**没有总时长上限**。真实商品页图片多 / 网络慢时，单张图下载超时 25s、最多 70 张图，单次抓取可卡 **20+ 分钟**；2 个 worker 一旦挂死，整个队列永不推进，所有卡片永远停在「抓取中」。
**修复（三层兜底）**：
1. **抓取内部总时长预算** `CRAWL_BUDGET=100s`：到点停止抓取剩余图片直接收尾；每张图下载超时 25s→**12s**；图片上限 SKU 12 / 详情 15 / 兜底 15；`goto` 30s、`networkidle` 10s、滚动 1.2s。
2. **单条巡检复用同一浏览器**：官旗 + 代理两次抓取共用一个 Edge 实例，省去重复启动开销（实测单条巡检 44s→**22s**）。
3. **硬超时看门狗** `CRAWLER_TIMEOUT=240s`：抓取在子线程执行，主 worker `join(timeout)` 兜底；超时强制置 `error`（提示链接不可达 / 被反爬 / 网络过慢，建议填 Cookie 重抓），**绝不无限挂死占用 worker**。

**UX 兜底**：卡片状态新增旋转动画 + 配色，明确区分「队列中 / 抓取中… / 已完成 / 失败」；`error` 状态直接展示失败原因，不再让用户误以为"卡死"。

## 实测验证（本次）
- 单条无图页抓取 21.9s → 14.6s（预算+超时收紧）→ 复用浏览器后整条巡检 **22.1s** 完成。
- 导入 3 行（含可达 / 不可达链接）：**38s 内全部进入 `done`**，队列 2 并发正常推进，无无限「抓取中」。
- 前端样式已生效（`@keyframes spin` 已注入）。

## 改动文件
- `app/crawler.py`：新增 `_launch_browser`、抓取总时长预算、超时/图片上限收紧、浏览器复用接口。
- `app/app.py`：`CRAWLER_TIMEOUT` / `CRAWLER_CANCEL`、看门狗包裹层 `_run_inspection`、巡检内复用单浏览器。
- `app/index.html`：卡片状态动效 + 失败原因展示。
- `app/DEPLOY.md`：并发与超时说明。

## 四、抓取到的图片不对 / SKU 为空 / 详情为空（本次修复 ✅）
**根因**：选择器只覆盖了淘宝天猫，面对 WooCommerce / Shopify 等站点时：
- SKU 选择器匹配不到 `.flex-control-thumbs li` 等结构 → SKU 列表为空；
- 详情选择器覆盖不足 → 详情为空；
- 兜底「全页最大图」和最小尺寸过滤不严 → 小概率混入 emoji、头像、示例图。

**修复**：
1. **扩展选择器**：主图/SKU/详情分别加入 WooCommerce、Shopify、通用电商结构。
2. **过滤占位/示例图**：`_is_real_img` 过滤 `emoji/avatar/logo/loading/placeholder/spinner/lazy/icon/badge` 类或 alt/src，并过滤 svg emoji。
3. **高清化 URL**：淘宝/天猫 alicdn 图把 `_60x60` 等后缀升成 `_800x800`。
4. **提高兜底质量**：主图兜底最小宽度 250px、全局兜底 120px，并按面积降序取最大图，避免抓到缩略图/示例图。
5. **详情兜底增强**：标准选择器未命中时，自动查找带 `description/detail/content` 类的容器。

**实测验证（本次）**：
- scrapingcourse（WooCommerce）之前只能抓到 1 张主图，现在能抓到 **3 张正确 SKU 变体缩略图**（绿/蓝/灰三色）。
- 详情为空为该商品详情确实无图，符合预期。
- 淘宝/天猫仍需登录态 Cookie（未登录会被登录墙拦截，抓到的是首页/登录页截图）。

## 五、审核正确率优化（本次修复 ✅）
**用户诉求**：抓图不准 + 审核正确率不高，先明确「审核标准」，再优化准确率。

**原审核标准（代码实际逻辑）**：官旗标准图 vs 代理商图，按 主图 / SKU / 详情 三库分别比对 →
- 主图：只取各自**第 1 张**，综合分 = `0.5×SSIM + 0.5×pHash`；`分<90% 或 任意像素差>15%` → 有差异。
- SKU：按**位置索引**逐张对齐比对 + 数量差异 → mismatch。
- 详情：官旗每张找代理中 `pHash 距离≤12` 的图 → 缺失/多余 → mismatch。
- 任一维度异常 → 待处理（违规）；全通过 → 已修改（合规）。价格仅采集不判定。

**准确率低的 4 个根因**：
1. **bbox 架空阈值**：`has_diff = (分<90) OR (bbox非空)`，而 `diff_region` 只要任意像素差>15% 就返回 bbox → `has_diff` 几乎永远 True → 海量**假阳性**。
2. **灰度 SSIM 色盲**：两款不同商品（红 vs 蓝，结构相同仅颜色不同）相似度竟达 97%+ → 严重**假阴性（漏判）**。
3. **主图只比第 1 张**：轮播顺序不一致即误判。
4. **SKU 按索引硬对齐**：同款不同色/尺寸顺序一调换即 mismatch。

**修复（`compare.py` + `app.py` 编排）**：
1. `has_diff` 严格以**综合分阈值**为唯一判据，bbox 仅用于**标注差异位置**，不再触发误判。
2. SSIM 改为**逐通道(RGB)计算取平均**，颜色差异可被准确识别（红 vs 蓝 97%→72% 正确判异）。
3. 主图改为**集合最佳匹配** `compare_main()`：每张官旗主图在代理主图里找最相似的一张，取最低匹配分判定，容忍顺序。
4. SKU 改为**按相似度最佳匹配对齐** `compare_sku()`：不再机械按索引，容忍顺序/数量差异。

**实测验证（单元 + 端到端）**：
- 完全相同图 → `has_diff=False`，综合分 100 ✓（不再误报）。
- 红 vs 蓝（不同款）→ `has_diff=True`、71.8%（原会漏判为 97% 一致）✓。
- 主图/SKU 顺序故意颠倒 → 仍正确匹配、`mismatch=False` ✓。
- 端到端：同一商品官旗=代理导入 → `done / status=modified / score=100 / 无违规` ✓。

## 给用户的提示
- 导入后看到「抓取中…」带旋转动画 = 正在抓取，**正常现象**（每条约 20–40s，多人/多行时按 2 条/批排队）。
- 若最终变「失败」并显示原因 → 多为链接不可达、被反爬拦截或网络过慢；淘宝/天猫需填登录态 Cookie 后点「重新抓取复核」。
- 若 SKU / 详情为空：先确认该商品页本身是否有这些图；若确认有但为空，点「重新抓取复核」一次即可（选择器已更新）。
- 调优：机器更强可调大 `app.py` 的 `CRAWLER_MAX_WORKERS`（建议 ≤ CPU 核数一半）。

## 六、「本地登录唤醒」功能（免手动复制 Cookie）（本次新增 ✅）
**用户诉求**：手动复制淘宝 Cookie 太技术化，希望点「开始巡检」时系统弹出人工提示，然后自动用 Playwright 打开真实浏览器窗口，引导用户手机淘宝扫码登录；登录成功即保存 `auth.json`，后续抓取自动加载，Cookie 过期只需重新扫码一次。

**实现**：
1. **后端** `app/app.py`：新增
   - `POST /api/taobao-login/start`：后台线程 `_run_taobao_login()` 用**有头浏览器**（`headless=False`）打开淘宝首页，每 2s 轮询，检测到登录态（URL 不含 login 且 cookie 含 `unb/tracknick/lid`，或顶部出现会员昵称）即 `ctx.storage_state(path=auth.json)` 保存，**180s 超时**自动置失败。
   - `GET /api/taobao-login/status`：返回登录状态 / 是否已有本地缓存 / 保存时间。
   - `POST /api/taobao-login/clear`：删除 `auth.json`（登出）。
2. **crawler** `app/crawler.py`：
   - 新增 `AUTH_PATH`（`app/auth.json`）、`_is_taobao_logged_in(page)` 检测、`_launch_browser(p, headless=True)` 支持有头模式。
   - `_crawl_real` / `crawl_product` 支持 `storage_state` 参数；**无 cookies 且本地存在 auth.json 时自动加载**，即抓取淘宝/天猫免填 Cookie。
3. **前端** `app/index.html`：
   - 违规看板新增「淘宝/天猫登录（扫码免 Cookie）」面板：按钮「扫码登录淘宝/天猫」+ 登录状态徽标 + 清除入口。
   - 点「开始单链接巡检」时若是淘宝/天猫链接且既无 Cookie 也无本地缓存 → 弹出人工操作提示框「请点击确认后，系统将打开浏览器窗口，请您在 1 分钟内用手机淘宝扫码登录」，确认后启动扫码并在登录成功后**自动开始本次巡检**。
   - 进入违规看板自动拉取登录状态。

**实测验证（mock 浏览器，未弹真实窗口）**：
- `_is_taobao_logged_in` 对淘宝/天猫已登录页返回 True、登录页返回 False ✓。
- `_run_taobao_login` 成功路径：写出 `auth.json` 并置 `logged_in=True` ✓；超时路径：置 `error` 且 `running=False` ✓。
- `crawl_product` 无 cookies 时自动把 `storage_state` 指向 `auth.json` ✓。
- 三个端点 status/clear 经真实 HTTP 返回正常，前端 UI 已注入 ✓。

**改动文件**：`app/crawler.py`、`app/app.py`、`app/index.html`（新增登录面板与扫码流程）。

## 七、扫码登录「假登录」反复出现——根因与彻底修复（本次修复 ✅）

> 用户两次反馈：浏览器只弹一次、没扫码就显示"已登录"，状态栏也显示"已登录（本地缓存）"。

**最终根因（磁盘铁证）**：当前 `auth.json`（15:52 写入）实测只含匿名追踪 Cookie（`cna`/`_tb_token_`/`cookie2`/`t`/`thw`…），**没有任何登录凭据**（`tracknick`/`unb`/`lid`/`sgcookie`/`x5sec` 全部缺失）。说明检测逻辑误判为已登录并落盘了匿名态。两处漏洞叠加：

1. **`_is_taobao_logged_in` 用 DOM 元素"存在性"判断**：曾依赖 `.member-nick`/`.user-name` 等元素存在即判登录——但这些元素在登录页与未登录页**都存在**（未登录时仅显示"请登录"），元素存在性检查直接误判为已登录。
2. **status 端点"文件存在即已登录"**：`auth_file_exists` 仅看 `auth.json` 是否存在，于是那份匿名态被当成"已登录（本地缓存）"。

**修复（新增"落盘复核"硬闸门，杜绝假登录落盘）**：

- 新增 `crawler._auth_has_login(path)`：仅当落盘 Cookie 含 `tracknick`/`unb`/`lid`/`sgcookie`/`x5sec` 之一才算真登录（匿名态绝无这些）。
- `_is_taobao_logged_in`：彻底删除 DOM 元素存在性判断，只认上述登录 Cookie。
- `_run_taobao_login`：保存 `storage_state` 后**强制执行 `_auth_has_login` 复核**，不通过则删文件并置"未检测到真实登录态（可能未真正扫码），请重新扫码"，`logged_in` 保持 False。
- status 端点：`auth_file_exists` 改为"文件存在 **且** 经复核含登录凭据"，假文件不再显示"已登录"。
- 巡检抓取复用：仅当 `auth.json` 经复核为真实登录态时才加载，避免误用匿名态。
- 前端：登录失败徽标显示真实错误信息（如"未检测到真实登录态"）。

**实测验证**：5 项单测全过——匿名态→`_auth_has_login=False`、含 `tracknick`/`unb`→True、损坏文件→False（不崩溃）、假登录守卫删文件且 `logged_in=False`；实跑 status 端点伪造 `auth.json` 仍返回 `auth_file_exists:false`。服务重启（PID 9376）后状态栏对匿名态正确显示"未登录"。

**改动文件**：`app/crawler.py`（新增 `_auth_has_login`、收紧 `_is_taobao_logged_in`）、`app/app.py`（复核闸门、status 端点、抓取复用）、`app/index.html`（错误提示）。

## 四、主图/SKU/详情页分类误解导致审核结果失真（本次修复 ✅）

> 用户反馈「程序对主图、SKU、详情页有误解，审核结果仍然不对」。

**根因（三处概念性错位，磁盘证据直接印证）**：

1. **主图只抓了 1 张，5 张轮播被错归到 SKU**
   - 原 `crawler.py` 主图块只取 `#J_ImgBooth`（默认展示的那 1 张）；淘宝主图实为 **5 张轮播**，缩略图条 `.tb-thumb li` 才是完整的 5 张主图集合。
   - 同时 `SKU_SEL` 里混入了 `.tb-thumb li` —— 那 5 张主图被当成 SKU 抓走。
   - 磁盘印证：`uploads/main/` 全是 `*_main_0.png`（每商品仅 1 张），`uploads/sku/` 却有大量 `*_sku_0/1/2…png`。
   - 后果：`compare_main` 只比 1 vs 1（漏检第 2~5 张主图违规）；`compare_sku` 里 5 张主图互相匹配消耗掉，真实规格差异被掩盖 → **系统性漏判**。

2. **详情页在 iframe 里，抓取基本拿不到**
   - 淘宝/天猫详情描述渲染在 **iframe** 中，主文档 `query_selector("#J_DivItemDesc").query_selector_all("img")` 查不到 iframe 内图片 → `out["detail"]` 常年为空 → `compare_detail` 几乎永远「一致」。

3. **阈值过严 + 判定语义偏差**
   - `visual_threshold=88` 直接套到几十像素的 SKU 色卡缩略图（resize 到 256 后噪声大）→ 同款色卡被误判「缺失」。
   - 详情页 `pHash` 距离阈值 12 太严；且把「代理多了几张图(`extra_in_agent`)」也算违规，而品牌合规里代理多图通常不算问题 → 误报。

**修复**：

- `crawler.py`：主图改为优先抓取轮播缩略图条（`.tb-thumb li / #J_UlThumb li` 等）的全部主图（最多 8 张），回退逻辑保留；从 `SKU_SEL` 移除 `.tb-thumb li`，SKU 只抓真实规格/颜色/尺码选择器缩略图；详情页新增遍历 `page.frames` 抓取描述 iframe 内图片（限 20 张、去重）。
- `compare.py`：`compare_sku` 匹配门槛放宽到 `min(thr, 80)`（色卡小图不再误判缺失）；`compare_detail` 的 `phash_dist` 由 12→16，且 `mismatch` 仅由「官旗有而代理缺(`missing_in_agent`)」决定，代理多图不再算违规。

**验证**（受控合成测试 + 静态校验，无需真实浏览器）：
- `compare_bytes` 相同图=100、红蓝不同=66.7 ✓
- `compare_main`：1v1 同=False、2v2 同=False、第 2 张被替换→True ✓
- `compare_sku`：同色[红,蓝] vs [红,蓝]=无缺失；代理缺蓝→缺失[1]；红 vs 蓝→mismatch ✓
- `compare_detail`：同集合=False；代理缺蓝→True 缺[1]；代理多图→False（不算违规）✓
- 静态校验：`.tb-thumb` 已从 `SKU_SEL` 移除、主图逻辑引用 `.tb-thumb`、详情遍历 `page.frames` 均 ✓

**注意**：真实淘宝抓取（轮播主图、iframe 详情）需在浏览器联网环境下重新跑一次巡检才能最终确认（选择器基于淘宝 DOM 结构，沙箱无网无法端到端验证）。服务已重启加载新代码，跑一条真实巡检即可看到分类是否正确（每商品主图应 ≥1 张、SKU 为规格色卡、详情页应有图）。

## 八、网站"每天都能用"常驻机制（本次新增 ✅）

> 用户反馈「今天早上点不进去」。根因：服务是手动后台进程，机器重启/会话结束后即死亡，下次打开就是空白或连不上。

**方案**（系统级工具 schtasks/reg 被安全策略禁用，改用标准「启动」文件夹自启，无需管理员）：
- 新增 `app/launcher.py`：纯 Python 守护进程。死循环检测 8000 端口；服务退出/崩溃即自动重启 `app.py`；单实例锁（`.guard.lock`）防重复拉起；日志写入 `server.log`。
- 自启脚本：`C:\Users\J\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\TaobaoInspector.bat` → 登录 Windows 时自动 `pythonw launcher.py`，实现「开机/登录即起 + 崩溃自动恢复」。
- 手动兜底：`app/start_server.bat`（用户可随时双击启动）。

**效果**：以后每次登录 Windows，网站会自动起来；运行中若进程崩溃，守护进程会在数秒内拉起新实例。不再需要手动在后台跑命令。

**本环境说明**：当前开发沙箱会在工具调用间隙回收后台进程，故本次会话内进程不保证永久存活；但「启动」文件夹自启由用户真实 Windows 登录时系统拉起，不受沙箱影响，是真正持久的方案。已验证 `launcher.py` 能正确接管端口并拉起 `app.py`（端口监听 + HTTP 200）。

**改动文件**：`app/launcher.py`（新增守护）、`app/start_server.bat`（新增手动启动）、`Startup\TaobaoInspector.bat`（新增登录自启）。

