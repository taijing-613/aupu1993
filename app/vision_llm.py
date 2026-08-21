"""多模态视觉大模型比对 —— 真正的「AI 视觉合规」语义级巡检。

默认走 OpenAI 兼容接口（GPT-4V / gpt-4o），可通过 base_url 切换到任意兼容服务
（通义千问VL、腾讯混元、Azure、本地 vLLM 等）。

安全约束：
  - API Key 一律从环境变量读取（VISION_API_KEY / OPENAI_API_KEY），
    不入库、不进代码、不进 Git。
  - 无 Key / 无网 / 模型异常时 available=False，由调用方回退到像素比对（compare.py），
    绝不因视觉层故障而阻断整个巡检流程。
"""
import base64
import io
import json
import os
import re

import requests
from PIL import Image

SYSTEM_PROMPT = (
    "你是电商视觉合规审核专家。给定「官旗标准图」与「代理商实况图」，"
    "判断代理商是否违反视觉合规。重点核查：①主图/商品图是否被替换、篡改、盗用或缺失；"
    "②是否存在违规文案、牛皮癣广告、夸大宣传、未授权 logo；"
    "③价格/促销信息与官旗是否明显不符；④SKU 规格图是否缺失或错配。"
    "注意：页面模板、背景、排版布局不同属正常现象，不应判违规；"
    "仅依据图像可见内容判断，不要臆测。必须以 JSON 回答："
    '{"verdict":"pass|violation|uncertain","type":["价格不符","违规文案"],'
    '"confidence":0.0~1.0,"reason":"一句话中文说明"}。'
)


def _resize_to_bytes(data: bytes, max_side: int = 512) -> bytes:
    """把图缩到最长边 <=512 的 JPEG，省 token、提速；失败原样返回。"""
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = img.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=82)
        return buf.getvalue()
    except Exception:
        return data


def _b64(data: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


def _extract_json(text: str):
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _call_once(off: bytes, ag: bytes, kind: str, model: str, base_url: str, api_key: str) -> dict:
    """调用一次视觉模型，返回结构化 dict；异常则 available=False。"""
    try:
        off_b = _b64(_resize_to_bytes(off))
        ag_b = _b64(_resize_to_bytes(ag))
        user = (f"【{kind}】左为官旗标准图，右为代理商实况图。"
                "请按系统要求判定代理商是否视觉违规，仅返回 JSON。")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": off_b}},
                    {"type": "image_url", "image_url": {"url": ag_b}},
                ]},
            ],
            "max_tokens": 400,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        resp = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload, timeout=60,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        data = _extract_json(content)
        if not isinstance(data, dict):
            return {"available": True, "verdict": "uncertain", "type": [],
                    "confidence": 0.0, "reason": "模型返回无法解析，已按不确定处理"}
        return {
            "available": True,
            "verdict": str(data.get("verdict", "uncertain")).lower(),
            "type": data.get("type") or [],
            "confidence": float(data.get("confidence", 0.0) or 0.0),
            "reason": str(data.get("reason", ""))[:300],
        }
    except Exception as e:  # noqa: BLE001
        return {"available": False, "verdict": "uncertain", "type": [],
                "confidence": 0.0, "reason": f"视觉模型调用失败：{str(e)[:160]}"}


def vision_compare(off: bytes, ag: bytes, kind: str, cfg: dict) -> dict:
    """对外主接口。cfg: {enabled, base_url, model}（api_key 内部从环境变量取）。"""
    if not cfg.get("enabled"):
        return {"available": False, "verdict": "uncertain", "type": [], "confidence": 0.0,
                "reason": "视觉模型未启用（项目设置中未开启）"}
    # 本地无网/无 Key 时的 mock：用于把整条巡检流程跑通验证，不消耗真实 API
    if os.environ.get("VISION_MOCK") == "1":
        return {"available": True, "verdict": "pass", "type": [],
                "confidence": 0.9, "reason": "[MOCK] 模拟视觉一致（仅用于本地流程验证）"}
    api_key = (cfg.get("api_key") or os.environ.get("VISION_API_KEY")
               or os.environ.get("OPENAI_API_KEY"))
    if not api_key:
        return {"available": False, "verdict": "uncertain", "type": [], "confidence": 0.0,
                "reason": "未配置视觉模型 API Key（请设置环境变量 VISION_API_KEY）"}
    base_url = cfg.get("base_url") or "https://api.openai.com/v1"
    model = cfg.get("model") or "gpt-4o"
    return _call_once(off, ag, kind, model, base_url, api_key)
