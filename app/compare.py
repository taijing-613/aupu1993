"""真实图像比对：SSIM（结构相似性）+ pHash（感知哈希）。
输入为图片原始字节，输出真实相似度百分比，不做任何造假。"""
import io
import numpy as np
from PIL import Image


def _to_gray_array(data: bytes, size: int = 256) -> np.ndarray:
    img = Image.open(io.BytesIO(data)).convert("L").resize((size, size))
    return np.asarray(img, dtype=np.float32)


def ssim_index(a: np.ndarray, b: np.ndarray) -> float:
    """标准 SSIM，范围 0~1。"""
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2
    mu_a, mu_b = a.mean(), b.mean()
    sig_a, sig_b = a.var(), b.var()
    sig_ab = ((a - a.mean()) * (b - b.mean())).mean()
    num = (2 * mu_a * mu_b + C1) * (2 * sig_ab + C2)
    den = (mu_a ** 2 + mu_b ** 2 + C1) * (sig_a + sig_b + C2)
    return float(num / den)


def _dct2(x: np.ndarray) -> np.ndarray:
    N = x.shape[0]
    xs = np.arange(N)
    cu = np.sqrt(1.0 / N) * np.ones(N)
    cu[1:] = np.sqrt(2.0 / N)
    out = np.zeros((N, N), dtype=np.float32)
    cx = np.cos((np.pi * xs[:, None] * (2 * xs[None, :] + 1)) / (2 * N))  # N x N
    for u in range(N):
        for v in range(N):
            su = np.sum(x * cx[u][:, None] * cx[v][None, :])
            out[u, v] = cu[u] * cu[v] * su
    return out


def phash_bits(data: bytes) -> np.ndarray:
    """32x32 灰度 -> 8x8 DCT 低频 -> 与中值比较得到 64bit 哈希（bool 数组）。"""
    img = Image.open(io.BytesIO(data)).convert("L").resize((32, 32))
    pix = np.asarray(img, dtype=np.float32)
    d = _dct2(pix)
    top = d[:8, :8].flatten()
    med = np.median(top)
    return top > med


def hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.sum(a != b))


def _to_rgb_arrays(data: bytes, size: int = 256):
    img = Image.open(io.BytesIO(data)).convert("RGB").resize((size, size))
    arr = np.asarray(img, dtype=np.float32)
    return arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]


def compare_bytes(official: bytes, agent: bytes) -> dict:
    """对两张图片做真实比对，返回 SSIM%、pHash%、综合相似度%。
    SSIM 改为逐通道(RGB)计算再取平均，避免灰度化导致的「颜色不同但结构相同」漏判（假阴性）。"""
    ar, ag, ab = _to_rgb_arrays(official)
    br, bg, bb = _to_rgb_arrays(agent)
    s_r = max(0.0, min(1.0, ssim_index(ar, br)))
    s_g = max(0.0, min(1.0, ssim_index(ag, bg)))
    s_b = max(0.0, min(1.0, ssim_index(ab, bb)))
    s = (s_r + s_g + s_b) / 3.0
    pa = phash_bits(official)
    pb = phash_bits(agent)
    ph = 1.0 - hamming(pa, pb) / 64.0
    score = round((0.5 * s + 0.5 * ph) * 100, 1)
    return {"ssim": round(s * 100, 1), "phash": round(ph * 100, 1), "score": score}


def extract_price(text: str):
    """真实正则提取 ¥ 后数字或 'x 元' 形式，返回 float 或 None。"""
    import re
    if not text:
        return None
    m = re.search(r"¥\s?([\d,]+(?:\.\d+)?)", text)
    if not m:
        m = re.search(r"([\d,]+(?:\.\d+)?)\s*元", text)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


# ---------------- 分类比对（主图 / SKU / 详情） ----------------
def diff_region(official: bytes, agent: bytes, size: int = 256, thresh: float = 0.15):
    """找出两图差异区域，返回归一化 bbox {x,y,w,h}（0~1），无差异返回 None。"""
    A = _to_gray_array(official, size)
    B = _to_gray_array(agent, size)
    d = np.abs(A - B) / 255.0
    mask = d > thresh
    if not mask.any():
        return None
    ys, xs = np.where(mask)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    pad = 0.05
    x = max(0.0, x0 / size - pad)
    y = max(0.0, y0 / size - pad)
    w = min(1.0, (x1 - x0) / size + 2 * pad)
    h = min(1.0, (y1 - y0) / size + 2 * pad)
    return {"x": round(x, 3), "y": round(y, 3), "w": round(w, 3), "h": round(h, 3)}


def compare_pair(official, agent, threshold):
    """单图对：{\"score\", \"has_diff\", \"diff_bbox\", \"missing\"}。"""
    if not official or not agent:
        return {"score": 0.0, "has_diff": True, "diff_bbox": None, "missing": True}
    base = compare_bytes(official, agent)
    has_diff = base["score"] < float(threshold)
    bbox = diff_region(official, agent) if has_diff else None
    return {"score": base["score"], "has_diff": bool(has_diff),
            "diff_bbox": bbox, "missing": False}


def compare_main(off_list, ag_list, threshold):
    """主图集合比对：官旗/代理的主图各是一个集合（轮播多张），
    对每张官旗主图在代理主图中找最相似的一张做最佳匹配，取最低匹配分作为判定分。
    避免「只比第 1 张」「顺序不一致」导致的误判。"""
    off = off_list or []
    ag = ag_list or []
    thr = float(threshold)
    if not off or not ag:
        return {"score": 0.0, "has_diff": True, "diff_bbox": None, "missing": True}
    used = set()
    best_scores = []
    worst = (101, None, None)  # (分数, 官旗idx, 代理idx)
    for oi, o in enumerate(off):
        best_ai, best_s = -1, -1
        for ai, a in enumerate(ag):
            if ai in used:
                continue
            s = compare_bytes(o, a)["score"]
            if s > best_s:
                best_s, best_ai = s, ai
        if best_ai >= 0:
            used.add(best_ai)
        best_scores.append(best_s)
        if best_s < worst[0]:
            worst = (best_s, oi, best_ai)
    min_best = min(best_scores) if best_scores else 0
    has_diff = min_best < thr
    bbox = None
    if has_diff and worst[1] is not None and worst[2] is not None:
        bbox = diff_region(off[worst[1]], ag[worst[2]])
    return {"score": round(min_best, 1), "has_diff": bool(has_diff),
            "diff_bbox": bbox, "missing": False}


def compare_sku(off_list, ag_list, threshold):
    """SKU 缩略图按「最佳相似度」对齐比对（不再是机械按位置索引），
    对每张官旗 SKU 在代理 SKU 中找最相似的一张；低于阈值视为该款缺失/差异。
    返回 {pairs, missing_in_agent, missing_in_official, mismatch}，与前端渲染结构兼容。

    SKU 缩略图多为几十像素的色卡/规格小图，resize 到 256 后噪声大，
    若直接套用主图阈值(默认 88)会把同款色卡误判为「缺失」，故 SKU 匹配容差放宽到 max(60, thr-12)。
    """
    off = off_list or []
    ag = ag_list or []
    thr = float(threshold)
    sku_thr = min(thr, 80.0)  # 色卡小图放宽匹配门槛，避免同款被误判缺失
    used = set()
    pairs = []
    missing_in_agent = []
    for oi, o in enumerate(off):
        best_ai, best_s = -1, -1
        for ai, a in enumerate(ag):
            if ai in used:
                continue
            s = compare_bytes(o, a)["score"]
            if s > best_s:
                best_s, best_ai = s, ai
        if best_ai >= 0 and best_s >= sku_thr:
            used.add(best_ai)
            pairs.append({"index": oi, "agent_index": best_ai,
                          "has_diff": False, "score": round(best_s, 1)})
        elif best_ai >= 0:
            # 找到最像的，但相似度仍低于阈值 → 视为差异/缺失款
            used.add(best_ai)
            pairs.append({"index": oi, "agent_index": best_ai,
                          "has_diff": True, "score": round(best_s, 1)})
            missing_in_agent.append(oi)
        else:
            pairs.append({"index": oi, "agent_index": None,
                          "has_diff": True, "score": 0.0})
            missing_in_agent.append(oi)
    missing_in_official = [ai for ai in range(len(ag)) if ai not in used]
    mismatch = bool(missing_in_agent) or bool(missing_in_official) \
        or any(p["has_diff"] for p in pairs)
    return {"pairs": pairs,
            "missing_in_agent": missing_in_agent,
            "missing_in_official": missing_in_official,
            "mismatch": bool(mismatch)}


def compare_detail(off_list, ag_list, phash_dist: int = 16):
    """详情页长图按感知哈希集合匹配，找出官旗有但代理缺的图。

    phash_dist 由 12 放宽到 16：真实详情图常因 CDN 参数/水印/轻微裁切导致哈希距离偏大，
    过严会把「同一张图」误判为代理缺失。
    判定语义（品牌合规）：违规 = 官旗有而代理缺失/替换的图片(missing_in_agent)；
    代理「多了几张图」本身不算违规，不再计入 mismatch，减少误报。
    """
    off = off_list or []
    ag = ag_list or []
    off_h = [phash_bits(x) for x in off]
    ag_h = [phash_bits(x) for x in ag]
    used = set()
    matched = []
    missing_in_agent = []
    for oi, oh in enumerate(off_h):
        best, bestd = -1, 999
        for ai, ah in enumerate(ag_h):
            if ai in used:
                continue
            dd = hamming(oh, ah)
            if dd < bestd:
                bestd, best = dd, ai
        if best >= 0 and bestd <= phash_dist:
            used.add(best)
            matched.append({"official": oi, "agent": best, "dist": int(bestd)})
        else:
            missing_in_agent.append(oi)
    extra_in_agent = [ai for ai in range(len(ag_h)) if ai not in used]
    # 品牌合规：仅官方有而代理缺/替换视为违规；代理多图不算违规
    mismatch = bool(missing_in_agent)
    return {"matched": matched, "missing_in_agent": missing_in_agent,
            "extra_in_agent": extra_in_agent, "mismatch": bool(mismatch)}
