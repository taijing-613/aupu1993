# 修复：扫码登录后网站一直显示「正在登录」

日期：2026-08-20

## 现象
用户用手机淘宝扫码后，网站仍停在「扫码登录中…」（前端 `st.running` 一直为 true），直到 180 秒超时。

## 根因（定位在 `app/crawler.py` 的 `_is_taobao_logging_in`）
旧逻辑开头有一句「只要页面 URL 含 login / passport 就直接 return False」：

```python
url = (page.url or "").lower()
if "login" in url or "passport" in url:
    return False          # ← 提前返回，漏检
cookies = page.context.cookies() ...
```

而淘宝扫码登录成功后，**常在 `login.taobao.com` 域名下停留、显示「登录成功」并写入登录态 Cookie**，此时 URL 仍含 `login`。旧代码一看到 URL 含 login 就判定未登录、根本没去检查 Cookie，于是即便用户已扫码、`tracknick` 等登录态 Cookie 已写入，也永远返回 False → 前端一直「正在登录」。

## 修复内容
1. **检测改为「只看 Cookie、不看 URL」**：只要命中登录态强信号 Cookie（`tracknick` / `x5sec` / `sgcookie`）即视为已登录，URL 不再参与拦截。
2. **补充兜底**：额外读取 `document.cookie` 二次确认，避免个别情况下 `context.cookies()` 读取时差。
3. **统一登录态判据**：`_auth_has_login`（落地文件复核）与运行时检测使用同一组强信号；移除了 `unb`/`lid`（已证实匿名访客也会携带，会误判）。
4. **加诊断字段**：`/api/taobao-login/status` 现在返回 `cookie_hits`（命中的登录态 Cookie 名）与 `page_host`（当前页 host），万一仍失败可直接定位卡在哪。

## 附带修复：重启时服务崩溃（readonly database）
清掉旧进程重启时，发现守护进程存在「重复守护」遗留，两个 launcher 各拉起一个 app.py，二者并发执行 `db.init()` 写库，触发 `sqlite3.OperationalError: attempt to write a readonly database`，导致崩溃循环。
- 处理：清除重复进程，改用单个干净实例运行；WAL 模式下单实例可正常读写。
- 注：`.guard.lock` 因环境「安全删除」钩子无法直接删除，但其中是已死亡的旧 PID，launcher 会自行覆盖，不影响。

## 当前状态
- 服务已在 http://127.0.0.1:8000 用新代码运行，启动无报错，`/api/taobao-login/status` 已返回新增诊断字段。
- 扫码登录逻辑：弹出浏览器 → 手机淘宝扫码并**在手机上点「确认登录」** → 浏览器写入登录态 Cookie → 后端检测到即保存 `auth.json` 并置「已登录」。

## 若仍异常，请用诊断字段反馈
扫码确认后若仍卡住，打开浏览器控制台看 `/api/taobao-login/status` 的返回：
- `cookie_hits` 为空 → 说明手机端未真正完成登录（只扫了码但没点「确认登录」，或二维码过期）。
- `page_host` 仍是 `login.taobao.com` 且 `cookie_hits` 有值 → 检测已生效，应已置登录。
