"""真实网页抓取（Playwright），按「分类抓取」策略将图片分库存储。

设计目标：放弃全店爬取，改为「精准对照表」——系统只抓取用户明确给出的单条链接，
并把它按三类分库落盘，杜绝全店抓取导致的商品错配：
  - uploads/main/      主图（页面第一张放大图）
  - uploads/sku/       SKU 缩略图列表（颜色/尺码切换的小图，按出现顺序存为数组）
  - uploads/detail/    详情页长图（详情描述里的所有图片）

抓取策略（确保「一定能抓到图」）：
  1. 真实加载页面（networkidle + 滚动触发懒加载）。
  2. 对每个候选 <img> 解析真实地址：src / data-src / data-original / data-lazy-src / srcset。
  3. 优先用 requests 带着浏览器请求头直接「下载真实图片字节」；
     若被反爬拦截（403 等）或下载失败，则退而用浏览器「元素截图」拿到已渲染的真实像素。
  4. 全局兜底：若三大分类都空，则把页面里所有有效图片（去重后）全部抓取，保证非空。

仅当 Playwright 未安装 / 页面完全加载失败时，才降级为确定性合成图（simulated=True）。
"""
import os
import re
import json
import time
import uuid
import random
from urllib.parse import urljoin, urlparse

# 单次真实抓取的「总时长预算」：到点后停止抓取剩余图片，直接收尾（避免某条链接
# 图片极多 / 网络极慢时，单次抓取挂死几十分钟，导致有界线程池被永久占用、全队列卡死）。
CRAWL_BUDGET = 100

import requests
from PIL import Image, ImageDraw

import db  # 仅用于 UPLOAD 路径常量

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOAD = db.UPLOAD
# 本地登录唤醒：扫码登录成功后把浏览器存储状态（cookies + localStorage）落盘到此文件，
# 后续所有抓取任务直接加载它，免重复手动复制 Cookie。
AUTH_PATH = os.path.join(BASE, "auth.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
IMG_HEADERS = {
    "User-Agent": UA,
    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _edge_path():
    """优先复用本机已安装的 Edge（Chromium 内核），免下载浏览器。找不到返回 None。"""
    cands = [
        r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%/Microsoft/Edge/Application/msedge.exe"),
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _slug(url: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:12]


def _parse_cookies(raw):
    """把浏览器复制的 Cookie 字符串（'k=v; k2=v2'）解析为 Playwright add_cookies 需要的 list。

    淘宝/天猫的登录态 cookie 需要在 .taobao.com / .tmall.com / .alicdn.com 等多个域下生效，
    这里为每个相关域各写一份，让浏览器按 domain 自动匹配。也兼容已传 list[dict] 的情况。
    """
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    raw = str(raw).strip()
    if not raw:
        return []
    # 若用户直接贴了 JSON 数组（list of dict），尝试解析
    if raw.startswith("[") and "name" in raw:
        try:
            import json as _json
            arr = _json.loads(raw)
            if isinstance(arr, list):
                return arr
        except Exception:
            pass
    out = []
    domains = [".taobao.com", ".tmall.com", ".alibaba.com", ".alicdn.com",
               "item.taobao.com", "detail.tmall.com"]
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip(); v = v.strip()
        if not k:
            continue
        for dom in domains:
            out.append({"name": k, "value": v, "domain": dom, "path": "/"})
    return out


def _extract_price(text: str):
    if not text:
        return None
    m = re.search(r"¥\s?([\d,]+(?:\.\d+)?)", text)
    if not m:
        m = re.search(r"([\d,]+(?:\.\d+)?)\s*元", text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


# 真实抓取用的选择器（覆盖主流电商 / 官网 / 淘宝天猫 / WooCommerce / Shopify 页面结构）
MAIN_SEL = [
    # 淘宝天猫
    "#J_ImgBooth", ".tb-main-pic img", ".tb-pic img", ".tb-booth img",
    ".tb-gallery img", ".tb-main-image img", ".main-image img",
    # WooCommerce
    ".wp-post-image", ".zoomImg", ".woocommerce-product-gallery__image img",
    ".woocommerce-product-gallery img",
    # Shopify / 通用
    "[data-image-index='0'] img", ".gallery-img img", ".product-image img",
    ".product-media img", ".product__media img", ".media-image img",
    ".p-img img", ".jqzoom img", ".cloud-zoom-image", ".preview-img img",
    ".product-gallery img", ".pi-Gallery img", ".spec-img img",
]
SKU_SEL = [
    # 淘宝天猫（仅「规格/颜色/尺码」选择器的缩略图，注意：主图轮播缩略条 .tb-thumb 不属于 SKU）
    ".tb-sku li", ".sku-line li", ".tb-prop li",
    ".J_TSaleProp li", ".prop-items li", ".sku-property-item",
    # WooCommerce
    ".flex-control-nav li", ".flex-control-thumbs li",
    ".woocommerce-product-gallery__image",
    ".woocommerce-product-variation .option", ".variations label",
    # Shopify / 通用
    ".sku-list-item", "li.sku-item", "[data-sku]", ".prop-items",
    ".sku-thumb", ".J_TSaleProp", ".sku-item",
    ".sku-box li", ".color-list li", ".size-list li",
    ".variant-option", ".swatch", ".product-form__input label",
    ".product-form__variants label", ".color-swatch", ".size-swatch",
]
DETAIL_SEL = [
    # 淘宝天猫
    "#J_DivItemDesc", ".tb-item-description", ".desc-content", ".detail-desc",
    ".item-description", "#detail", ".tb-detail", "#J_Detail",
    # WooCommerce / Shopify / 通用
    "#tab-description", ".woocommerce-product-details__short-description",
    ".woocommerce-Tabs-panel--description", ".product-description",
    ".product__description", ".product-details__description",
    ".entry-content", ".description", ".goods-desc", ".detail-content",
    ".product-detail", ".detail-area", ".rich-text", ".product-intro",
]


def _ensure_dirs():
    for d in ("main", "sku", "detail"):
        os.makedirs(os.path.join(UPLOAD, d), exist_ok=True)


def _screenshot_el(el):
    """对单个元素截图拿字节（规避图片跨域 fetch 限制）。失败返回 None。"""
    try:
        el.scroll_into_view_if_needed()
        return el.screenshot()
    except Exception:
        return None


def _resolve_src(el, base_url):
    """从 img 元素解析最佳真实图片地址（含懒加载字段与 srcset），并尽量取高清。"""
    for attr in ("src", "data-src", "data-original", "data-lazy-src",
                 "data-lazy", "data-url", "data-ks-lazyload", "data-large_image",
                 "data-zoom-image", "data-thumb"):
        try:
            v = el.get_attribute(attr)
        except Exception:
            v = None
        if v and v.strip() and not v.strip().lower().startswith("data:"):
            return _to_hd_url(urljoin(base_url, v.strip()))
    try:
        ss = el.get_attribute("srcset")
    except Exception:
        ss = None
    if ss:
        parts = [p.strip() for p in ss.split(",") if p.strip()]
        if parts:
            return _to_hd_url(urljoin(base_url, parts[-1].split(" ")[0]))
    return None


def _download_bytes(url, referer):
    """直接下载真实图片字节；返回 bytes 或 None（反爬 403 / 超时 / 非图片）。

    淘宝/天猫图片走 img.alicdn.com 等 CDN，必须带淘宝站点域的 Referer 否则返回 403，
    因此当图片域名属于 alicdn 系时强制补 Referer。
    """
    try:
        h = dict(IMG_HEADERS)
        if referer:
            h["Referer"] = referer
        host = urlparse(url).netloc.lower()
        if "alicdn" in host or "taobaocdn" in host or "tbcdn" in host:
            h["Referer"] = h.get("Referer") or "https://item.taobao.com/"
        r = requests.get(url, headers=h, timeout=12, allow_redirects=True)
        if r.status_code != 200 or not r.content:
            return None
        ctype = r.headers.get("Content-Type", "")
        # 校验确实是图片（避免抓到 HTML 错误页）
        if "image" in ctype or _looks_like_image(r.content):
            return r.content
    except Exception:
        return None
    return None


def _looks_like_image(b: bytes) -> bool:
    try:
        Image.open(__import__("io").BytesIO(b)).verify()
        return len(b) > 800
    except Exception:
        return False


def _is_real_img(el, min_w=30):
    """元素确为有效图片（已加载、非占位像素、非头像/emoji/logo）。"""
    try:
        w = el.evaluate("e=>e.naturalWidth")
        h = el.evaluate("e=>e.naturalHeight")
        if not (w and h and w >= min_w and h >= min_w):
            return False
        # 过滤明显非商品图：emoji、头像、logo、loading 占位
        cls = (el.get_attribute("class") or "").lower()
        alt = (el.get_attribute("alt") or "").lower()
        src = (el.get_attribute("src") or "").lower()
        bad_kw = ("emoji", "avatar", "logo", "loading", "placeholder", "lazyload",
                  "spinner", "skeleton", "lazy", "icon", "badge")
        if any(k in cls or k in alt or k in src for k in bad_kw):
            return False
        # 过滤 svg emoji（WordPress 常见 1f50d.svg 等）
        if ".svg" in src and ("emoji" in src or w <= 80):
            return False
        return True
    except Exception:
        return False


def _to_hd_url(url):
    """尝试把常见的压缩图 URL 还原为高清图。失败返回原 URL。"""
    if not url:
        return url
    # 淘宝/天猫 alicdn：xxx_60x60.jpg -> xxx.jpg 或 xxx_800x800.jpg
    if "alicdn.com" in url or "taobaocdn.com" in url or "tbcdn.com" in url:
        # 先尝试去掉 _60x60q90 之类的尺寸后缀
        u = re.sub(r"_\d+x\d+[^./]*(?=\.[a-z]+)", "_800x800", url, count=1)
        if u == url:
            # 没有尺寸后缀时直接加 _800x800
            u = re.sub(r"(\.[a-z]+)$", r"_800x800\1", url, count=1)
        return u
    # 京东
    if "jd.com" in url:
        return re.sub(r"/[ns]\d+x\d+_", "/n12/", url)
    return url


def _save(folder, name, data):
    path = os.path.join(UPLOAD, folder, name)
    with open(path, "wb") as f:
        f.write(data)
    return name


def _grab_one(el, folder, base, slug, idx, seen, referer):
    """抓取单个元素：先下载真实字节，失败用截图。返回文件名或 None。"""
    name = f"{slug}_{folder}_{idx}.png"
    # 去重：同一张图不重复保存
    try:
        key = el.evaluate("e=>e.currentSrc||e.src") or ""
    except Exception:
        key = ""
    if key and key in seen:
        return None
    if key:
        seen.add(key)
    # 跳过无 src 或 data: 占位图
    src = _resolve_src(el, base)
    if not src:
        return None
    # 方法一：下载真实图片字节（高清化后）
    data = _download_bytes(src, referer)
    if data:
        return _save(folder, name, data)
    # 方法二：浏览器元素截图（已渲染的真实像素）
    data = _screenshot_el(el)
    if data:
        return _save(folder, name, data)
    return None


def _scroll_load(page):
    """滚动页面以触发懒加载图片（缩短到 ~1.2s，避免无效等待）。"""
    try:
        for y in range(0, 5):
            page.evaluate(f"window.scrollTo(0, document.body.scrollHeight*{y}/4)")
            page.wait_for_timeout(250)
        page.evaluate("window.scrollTo(0,0)")
        page.wait_for_timeout(300)
    except Exception:
        pass


def _launch_browser(p, headless=True):
    """启动浏览器：优先复用本机 Edge 内核，失败回退 Playwright 自带 chromium。

    headless=False 用于「本地登录唤醒」——需要弹出真实浏览器窗口让用户手机扫码。
    """
    base_args = ["--no-sandbox", "--disable-dev-shm-usage",
                 "--disable-blink-features=AutomationControlled"]

    def _try(ep):
        kwargs = dict(headless=headless, args=list(base_args))
        if ep:
            kwargs["executable_path"] = ep
        return p.chromium.launch(**kwargs)

    ep = _edge_path()
    try:
        return _try(ep)
    except Exception:
        return _try(None)


# 判定「真实登录态」的强信号 Cookie（匿名访客绝不会携带，杜绝「假登录」误判）。
# unb / lid 曾被证实匿名访客也会携带（追踪 Cookie），故不再作为登录判据，
# 改用 tracknick(会员昵称) / x5sec(登录后安全票据) / sgcookie(安全网关 Cookie) 三者。
_LOGIN_COOKIES = ("tracknick", "x5sec", "sgcookie")


def _is_taobao_logged_in(page):
    """判断当前页面是否处于淘宝/天猫「真实」登录态（用于「本地登录唤醒」扫码检测）。

    判据只用代表真实登录态、匿名访客绝不会携带的 Cookie（见 _LOGIN_COOKIES）。
    不再依赖 DOM 元素「存在性」——登录页与未登录页都可能存在同名单元素（仅显示“请登录”），
    元素存在性检查会误判为已登录（这正是之前“假登录”的根因）。

    关键修复（2026-08-20）：检测「只看 Cookie、不看 URL」。
    扫码登录成功后淘宝常在 login.taobao.com 域名下显示「登录成功」并写入登录态 Cookie，
    此时 URL 仍含 "login"；旧逻辑一遇到 URL 含 login 就直接 return False，导致已经扫码、
    Cookie 已写入却一直被误判为「未登录」，前端永远停在「正在登录」直到超时。
    现在 Cookie 一旦命中即视为已登录，彻底不受 URL 干扰。
    """
    try:
        # 1) 优先取完整 cookie（含 HttpOnly），比 document.cookie 更全面准确
        try:
            cookies = page.context.cookies() or []
        except Exception:
            cookies = []
        names = {str(c.get("name", "")).lower() for c in cookies}
        for k in _LOGIN_COOKIES:
            if k in names:
                return True
        # 2) 兜底：部分登录态通过 JS 写入 document.cookie，再确认一次
        try:
            dc = (page.evaluate("document.cookie") or "")
            dcl = dc.lower()
            if any(k in dcl for k in _LOGIN_COOKIES):
                return True
        except Exception:
            pass
    except Exception:
        return False
    return False


def _auth_has_login(path):
    """复核 auth.json 是否真的含登录态凭据（杜绝「假登录」）。

    即便前端检测逻辑误判，保存前/读取时都按实际落盘的 Cookie 复核：
    仅当存在 tracknick/x5sec/sgcookie 中至少一项，才算真正的登录态。
    匿名访客虽带 cna / _tb_token_ / cookie2 / t / thw / unb / lid 等，但绝不含上述任一项。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        cookies = d.get("cookies", []) or []
        names = {str(c.get("name", "")).lower() for c in cookies}
        for k in _LOGIN_COOKIES:
            if k in names:
                return True
    except Exception:
        return False
    return False


def _crawl_real(url, slug, cookies=None, browser=None, storage_state=None):
    """真实抓取单条链接。browser 可传入已启动的浏览器实例以复用（单条巡检内官旗+代理共用一个），
    为 None 时自行启动并在结束时关闭。"""
    out = {"ok": True, "url": url, "title": None, "price": None,
           "main": [], "sku": [], "detail": [], "error": None,
           "simulated": False, "login_wall": False}
    deadline = time.monotonic() + CRAWL_BUDGET
    from playwright.sync_api import sync_playwright
    own = browser is None
    p = None
    try:
        if own:
            p = sync_playwright().start()
            browser = _launch_browser(p)
        ctx_kwargs = dict(
            viewport={"width": 1280, "height": 1400},
            user_agent=UA,
            locale="zh-CN",
        )
        if storage_state:  # 加载「本地登录唤醒」保存的登录态（auth.json）
            ctx_kwargs["storage_state"] = storage_state
        ctx = browser.new_context(**ctx_kwargs)
        if cookies:
            try:
                ck = _parse_cookies(cookies)
                if ck:
                    ctx.add_cookies(ck)
            except Exception:
                pass
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        _scroll_load(page)
        try:
            out["title"] = (page.title() or "").strip()[:80] or None
        except Exception:
            pass
        # 价格
        price = None
        for sel in [".tb-rmb-num", "#J_Price", ".p-price .price", ".price", "[class*=price]"]:
            try:
                txt = page.locator(sel).first.inner_text(timeout=700)
                price = _extract_price(txt)
                if price is not None:
                    break
            except Exception:
                continue
        if price is None:
            try:
                price = _extract_price(page.inner_text("body"))
            except Exception:
                pass
        out["price"] = price

        # 登录墙检测：淘宝/天猫未登录会跳登录页，抓到的不是商品图
        wall = ("登录" in (out["title"] or "") or "login" in (out["title"] or "").lower())
        try:
            if page.query_selector("#login-form, .mod-login, #nocaptcha, .login-box, "
                                   ".login-wrapper, #slide-code, .nc-container, .login-tip, "
                                   ".sg-login, .tb-login"):
                wall = True
        except Exception:
            pass
        out["login_wall"] = wall

        seen = set()
        base = page.url

        # 主图：淘宝/天猫主图是「5 张轮播」，缩略图条(.tb-thumb / #J_UlThumb)上的小图
        # 才是完整的 5 张主图集合；#J_ImgBooth 只是当前展示的那一张。
        # 过去只抓 #J_ImgBooth（1 张）→ 漏检第 2~5 张主图违规，且缩略图条被误归到 SKU。
        # 现改为：优先抓取轮播缩略图条的全部主图；拿不到再回退到主图大图选择器/最大图。
        main_els = []
        try:
            for li in page.query_selector_all(
                    ".tb-thumb li, #J_UlThumb li, .tb-gallery .tb-thumb li, "
                    ".main-image-thumbnails li, .pic-list li"):
                im = li.query_selector("img") if li else None
                # 缩略图元素本身只有 ~60px，但 _grab_one 会下载高清版，故仅要求 >=30
                if im and _is_real_img(im, 30):
                    main_els.append(im)
        except Exception:
            pass
        if not main_els:
            for s in MAIN_SEL:
                try:
                    el = page.query_selector(s)
                except Exception:
                    el = None
                if el and _is_real_img(el, 120):
                    main_els.append(el)
                    break
        if not main_els:
            try:
                els = page.query_selector_all("img")
                big = [e for e in els if _is_real_img(e, 250)]
                big.sort(key=lambda e: e.evaluate("e=>e.naturalWidth*e.naturalHeight"),
                         reverse=True)
                if big:
                    main_els.append(big[0])
            except Exception:
                pass
        # 去重保存全部主图（轮播集合，最多 8 张）
        _mseen = set()
        for i, el in enumerate(main_els[:8]):
            try:
                k = el.evaluate("e=>e.currentSrc||e.src") or ""
            except Exception:
                k = ""
            if k and k in _mseen:
                continue
            if k:
                _mseen.add(k)
            n = _grab_one(el, "main", base, slug, i, seen, base)
            if n:
                out["main"].append(n)

        # SKU 缩略图
        for s in SKU_SEL:
            try:
                els = page.query_selector_all(s + " img") or page.query_selector_all(s)
            except Exception:
                els = []
            # SKU 图典型尺寸 40~200px，过滤非商品占位
            els = [e for e in els if _is_real_img(e, 30)]
            # 去重并保留合理数量
            uniq = []
            ks = set()
            for e in els:
                try:
                    k = e.evaluate("el=>el.currentSrc||el.src") or ""
                except Exception:
                    k = ""
                if k and k in ks:
                    continue
                if k:
                    ks.add(k)
                uniq.append(e)
            if uniq:
                for i, el in enumerate(uniq[:12]):
                    if time.monotonic() > deadline:
                        break
                    n = _grab_one(el, "sku", base, slug, i, seen, base)
                    if n:
                        out["sku"].append(n)
                break

        # 详情页长图：淘宝/天猫的详情描述渲染在 iframe 内，主文档里直接 query 不到图；
        # 因此同时遍历页面 frame 抓取描述 iframe 内的全部图片。
        detail_els = []
        # 1) 主文档描述容器（部分站点描述不在 iframe）
        detail_containers = []
        for s in DETAIL_SEL:
            try:
                container = page.query_selector(s)
            except Exception:
                container = None
            if container:
                detail_containers.append(container)
                break
        if not detail_containers:
            # 兜底：查找带 description / content 类的 div
            for s in ["[class*='description']", "[class*='detail']", "[class*='content']",
                      "[id*='description']", "[id*='detail']"]:
                try:
                    container = page.query_selector(s)
                except Exception:
                    container = None
                if container:
                    detail_containers.append(container)
                    break
        for container in detail_containers:
            try:
                container.scroll_into_view_if_needed()
            except Exception:
                pass
            try:
                detail_els += [e for e in container.query_selector_all("img")
                               if _is_real_img(e, 80)]
            except Exception:
                pass
        # 2) 详情 iframe：淘宝/天猫描述在 iframe 中渲染，主文档拿不到其图片
        try:
            for fr in page.frames:
                if fr is page.main_frame:
                    continue
                u = (fr.url or "").lower()
                if not (("taobao" in u) or ("tmall" in u) or ("alicdn" in u)
                        or ("item" in u) or ("desc" in u) or ("detail" in u) or u == ""):
                    continue
                for im in fr.query_selector_all("img"):
                    if _is_real_img(im, 80):
                        detail_els.append(im)
        except Exception:
            pass
        # 去重并按出现顺序保存（详情页图很多，限 20 张）
        _dseen = set()
        _di = 0
        for el in detail_els[:20]:
            _di += 1
            try:
                k = el.evaluate("e=>e.currentSrc||e.src") or ""
            except Exception:
                k = ""
            if k and k in _dseen:
                continue
            if k:
                _dseen.add(k)
            n = _grab_one(el, "detail", base, slug, _di, seen, base)
            if n:
                out["detail"].append(n)

        # 全局兜底：若三大分类全空，抓取页面所有有效大图，确保非空
        if not (out["main"] or out["sku"] or out["detail"]):
            try:
                all_els = [e for e in page.query_selector_all("img")
                           if _is_real_img(e, 120)]
                # 去重按 currentSrc，并按面积降序保证主图质量
                uniq = []
                ks = set()
                for e in all_els:
                    try:
                        k = e.evaluate("e=>e.currentSrc||e.src") or ""
                    except Exception:
                        k = ""
                    if k and k in ks:
                        continue
                    if k:
                        ks.add(k)
                    uniq.append(e)
                uniq.sort(key=lambda e: e.evaluate("e=>e.naturalWidth*e.naturalHeight"),
                          reverse=True)
                for i, el in enumerate(uniq[:12]):
                    if time.monotonic() > deadline:
                        break
                    folder = "main" if i == 0 else "detail"
                    n = _grab_one(el, folder, base, slug, i, seen, base)
                    if n:
                        out[folder].append(n)
            except Exception:
                pass

    finally:
        if own:
            try:
                browser.close()
            except Exception:
                pass
            try:
                p.stop()
            except Exception:
                pass
    return out


def _synthetic_product(url, slug):
    """最后兜底：Playwright 不可用 / 页面完全加载失败时的确定性合成图。"""
    h = int(uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:8], 16)
    rnd = random.Random(h)
    colors = ["红", "蓝", "黑", "白", "金"]
    sections = ["材质", "尺码", "场景", "售后", "工艺"]

    def _blank(label):
        img = Image.new("RGB", (600, 600), "white")
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 600, 80], fill="#111827")
        d.text((20, 30), label, fill="white")
        return img, d

    img, d = _blank("PRODUCT MAIN")
    d.rectangle([40, 120, 560, 540], outline="#4F46E5", width=4)
    for _ in range(rnd.randint(3, 7)):
        x = rnd.randint(60, 500); y = rnd.randint(160, 500)
        w = rnd.randint(40, 120); hh = rnd.randint(40, 120)
        d.rectangle([x, y, x + w, y + hh], fill=(rnd.randint(220, 245),) * 3)
    main_name = slug + "_main.png"
    img.save(os.path.join(UPLOAD, "main", main_name))

    sku = []
    for i in range(rnd.randint(2, 4)):
        img, d = _blank("SKU " + colors[i % len(colors)])
        d.ellipse([200, 200, 400, 400], outline="#10B981", width=3)
        name = f"{slug}_sku_{i}.png"
        img.save(os.path.join(UPLOAD, "sku", name))
        sku.append(name)

    detail = []
    for i in range(rnd.randint(2, 4)):
        img, d = _blank("DETAIL " + sections[i % len(sections)])
        d.rectangle([40, 120, 560, 540], fill=(rnd.randint(235, 250),) * 3)
        name = f"{slug}_detail_{i}.png"
        img.save(os.path.join(UPLOAD, "detail", name))
        detail.append(name)

    return {"main": [main_name], "sku": sku, "detail": detail,
            "title": None, "price": round(rnd.uniform(99, 299), 2)}


def crawl_product(url: str, upload_dir: str = None, cookies=None, browser=None,
                  storage_state=None) -> dict:
    """分类抓取单条商品/店铺链接。

    返回：{ok, url, title, price, main:[文件名], sku:[文件名], detail:[文件名],
           error, simulated, login_wall}
    图片已落盘到 uploads/{main,sku,detail}/ 下。
    只要有任何真实图片抓到，simulated 即为 False。仅在 Playwright 缺失/完全失败时降级合成图。
    cookies：可选，浏览器复制的登录态 Cookie（淘宝/天猫未登录会被登录墙拦截，需填此项）。
    storage_state：可选，Playwright storage_state（auth.json 路径或 dict）。未传 cookies 且本地
        存在 auth.json 时，自动加载它——即「本地登录唤醒」保存的淘宝/天猫登录态。
    """
    _ensure_dirs()
    slug = _slug(url)
    # 未显式给 cookies / storage_state 时，自动复用本地登录唤醒保存的 auth.json
    if not cookies and not storage_state and os.path.exists(AUTH_PATH):
        storage_state = AUTH_PATH
    try:
        real = _crawl_real(url, slug, cookies=cookies, browser=browser,
                           storage_state=storage_state)
        if real["main"] or real["sku"] or real["detail"]:
            real["simulated"] = False
            return real
        # 真实抓取未拿到任何图：若是登录墙，明确提示需填 Cookie（不降级合成图）
        if real.get("login_wall"):
            real["simulated"] = False
            real["error"] = ("该页面需要登录态才能查看商品图（淘宝/天猫反爬限制）。"
                             "请在单链接巡检表单填写「淘宝/天猫登录态 Cookie」后重新抓取。")
            return real
        # 真实抓取未拿到任何图 -> 最后兜底合成
        syn = _synthetic_product(url, slug)
        out = {"ok": True, "url": url, "title": None, "price": None,
               "main": syn["main"], "sku": syn["sku"], "detail": syn["detail"],
               "error": "真实抓取未获得图片，已降级为演示图", "simulated": True,
               "login_wall": False}
        return out
    except Exception as e:
        syn = _synthetic_product(url, slug)
        return {"ok": True, "url": url, "title": None, "price": syn["price"],
                "main": syn["main"], "sku": syn["sku"], "detail": syn["detail"],
                "error": "真实抓取失败（" + str(e)[:160] + "），已降级为演示图",
                "simulated": True, "login_wall": False}
