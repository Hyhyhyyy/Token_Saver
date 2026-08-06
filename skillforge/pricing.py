"""模型定价表管理（F2 成本/延迟仿真）。

- 内置快照价（GPT-4o / Claude 3.5 Sonnet / 本地），标注日期与免责声明。
- 文件优先：DATA_DIR/pricing.json；缺失回退内置并落盘。
- save_pricing() 始终保留一条 `local-snapshot`（input=0）作为零成本对照基线。
- 所有金额单位：美元；单价单位：每 1k token。
"""
from __future__ import annotations

import json

from .config import PRICING_PATH, PRICING_AS_OF

# 本地零成本基线（对照用，永远保留）
_LOCAL_BASELINE: dict = {
    "model": "local-snapshot",
    "input_price_per_1k": 0.0,
    "output_price_per_1k": 0.0,
    "latency_overhead_ms": 2.0,
    "latency_per_token_ms": 0.002,
    "context_window": 32768,
}

DEFAULT_PRICING: dict = {
    "as_of": PRICING_AS_OF,
    "disclaimer": "示例快照价，仅供仿真参考，实际请以各厂商官方为准。",
    "models": [
        {
            "model": "gpt-4o",
            "input_price_per_1k": 0.0025,
            "output_price_per_1k": 0.01,
            "latency_overhead_ms": 20.0,
            "latency_per_token_ms": 0.02,
            "context_window": 128000,
        },
        {
            "model": "claude-3.5-sonnet",
            "input_price_per_1k": 0.003,
            "output_price_per_1k": 0.015,
            "latency_overhead_ms": 25.0,
            "latency_per_token_ms": 0.025,
            "context_window": 200000,
        },
        dict(_LOCAL_BASELINE),
    ],
}


def _ensure_local_baseline(models: list[dict]) -> list[dict]:
    if not any(m.get("model") == "local-snapshot" for m in models):
        models = list(models) + [dict(_LOCAL_BASELINE)]
    return models


def get_pricing() -> dict:
    """读取定价表；文件缺失或损坏则回退内置默认并落盘。"""
    if PRICING_PATH.exists():
        try:
            data = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("models"), list) and data["models"]:
                data["models"] = _ensure_local_baseline(data["models"])
                return data
        except Exception:
            pass
    PRICING_PATH.write_text(
        json.dumps(DEFAULT_PRICING, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {k: (list(v) if k == "models" else v) for k, v in DEFAULT_PRICING.items()}


def save_pricing(models) -> dict:
    """覆盖写入定价表（保留 as_of/disclaimer 与本地基线），返回完整结构。"""
    if not isinstance(models, list) or not models:
        raise ValueError("models 必须为非空数组")
    models = _ensure_local_baseline(models)
    out = {
        "as_of": PRICING_AS_OF,
        "disclaimer": "示例快照价，仅供仿真参考，实际请以各厂商官方为准。",
        "models": models,
    }
    PRICING_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
