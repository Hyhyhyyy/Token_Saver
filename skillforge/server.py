"""FastAPI 服务：暴露 REST API 并托管前端静态资源。"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .skill_parser import scan_skills, get_skill_by_id
from .validator import validate
from .cleaner import clean_skill
from .tracker import log_event, get_stats, get_series, get_leaderboard, get_skill_stats
from .tokenizer import BACKEND, count_tokens
from .spec import STANDARD_VERSION, SKILL_TEMPLATE, DESC_TEMPLATE, DESC_EXAMPLE, get_validation_rules
from . import config
from . import budget, gold, pricing, custom_rules, simulator, simbank
from .scorer import get_vectorizer, _load_vectorizer_config
import json

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="SkillForge · 技能精炼台", version=__version__)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__, "tokenizer": BACKEND, "skills_found": len(scan_skills())}


@app.get("/api/spec")
def spec():
    # 合并内置 + 自定义规则（标注 source）
    return {
        "standard_version": STANDARD_VERSION,
        "skill_template": SKILL_TEMPLATE,
        "desc_template": DESC_TEMPLATE,
        "desc_example": DESC_EXAMPLE,
        "rules": get_validation_rules(),
        "tokenizer": BACKEND,
    }


@app.get("/api/skills")
def list_skills():
    custom = custom_rules.load_custom_rules()
    out = []
    for s in scan_skills():
        v = validate(s, custom_rules=custom)
        out.append({
            "name": s["name"],
            "dir_name": s["dir_name"],
            "path": s["path"],
            "desc_tokens": s["desc_tokens"],
            "total_tokens": s["total_tokens"],
            "status": v["status"],
            "score": v["score"],
            "error_count": v["error_count"],
            "warning_count": v["warning_count"],
            "info_count": v["info_count"],
            "parse_error": s.get("parse_error"),
        })
    return {"count": len(out), "skills": out}


@app.get("/api/skills/{skill_id}")
def skill_detail(skill_id: str):
    s = get_skill_by_id(skill_id)
    if not s:
        raise HTTPException(404, "skill not found")
    custom = custom_rules.load_custom_rules()
    v = validate(s, custom_rules=custom)
    return {
        "name": s["name"],
        "dir_name": s["dir_name"],
        "path": s["path"],
        "frontmatter": s["frontmatter"],
        "body": s["body"],
        "body_raw": s["body_raw"],
        "desc_tokens": s["desc_tokens"],
        "total_tokens": s["total_tokens"],
        "validation": v,
        "parse_error": s.get("parse_error"),
    }


@app.post("/api/clean")
async def clean(request: Request):
    data = await request.json()
    skill_id = data.get("skill_id")
    use_llm = bool(data.get("use_llm", False))
    s = get_skill_by_id(skill_id)
    if not s:
        raise HTTPException(404, "skill not found")
    # 闭环：采用 effective_target 注入 cleaner（回归自动/手动回调后压缩更温和）
    target = budget.effective_target(skill_id)
    result = clean_skill(s, use_llm=use_llm, target=target)
    log_event(skill_id, "clean", result["before_desc_tokens"], result["after_desc_tokens"],
              note="; ".join(result["changes"]))
    return result


@app.post("/api/apply")
async def apply(request: Request):
    data = await request.json()
    skill_id = data.get("skill_id")
    serialized = data.get("serialized", "")
    # 防御：拒绝可能损坏技能文件的退化写入
    if not serialized.strip().startswith("---"):
        raise HTTPException(400, "序列化内容缺少 frontmatter，已拒绝写入")
    import tempfile
    tmp = Path(tempfile.mktemp(suffix=".md"))
    tmp.write_text(serialized, encoding="utf-8")
    from .skill_parser import parse_skill_file, description_tokens
    parsed = parse_skill_file(tmp)
    tmp.unlink()
    fm = parsed.get("frontmatter", {})
    if not fm.get("name") or not str(fm.get("description", "")).strip():
        raise HTTPException(400, "清洗结果缺少 name 或 description，已拒绝写入以防损坏")
    if parsed.get("parse_error"):
        raise HTTPException(400, f"清洗结果无法解析：{parsed['parse_error']}")

    s = get_skill_by_id(skill_id)
    if not s:
        raise HTTPException(404, "skill not found")
    path = Path(s["path"])
    # 备份原文件
    backup = path.with_suffix(".md.bak")
    if not backup.exists():
        shutil.copy(path, backup)
    path.write_text(serialized, encoding="utf-8")
    # 重新解析以统计实际节省
    new = parse_skill_file(path)
    after_tokens = description_tokens(new["frontmatter"])
    log_event(skill_id, "apply", s["desc_tokens"], after_tokens, note="已写回并备份原文件")
    return {"ok": True, "backup": str(backup), "after_desc_tokens": after_tokens}


@app.post("/api/track")
async def track(request: Request):
    data = await request.json()
    skill_id = data.get("skill_id")
    action = data.get("action", "call")
    tb = int(data.get("tokens_before", 0) or 0)
    ta = int(data.get("tokens_after", 0) or 0)
    eid = log_event(skill_id, action, tb, ta, note=data.get("note", ""))
    return {"ok": True, "event_id": eid}


@app.get("/api/stats")
def stats():
    st = get_stats()
    st["series"] = get_series()
    st["leaderboard"] = get_leaderboard()
    return st


@app.get("/api/tracking/{skill_id}")
def skill_tracking(skill_id: str):
    return get_skill_stats(skill_id)


# ============================ F1 调度反事实模拟 ============================

@app.get("/api/sim/gold")
def get_gold_samples():
    samples = gold.get_gold()
    return {"count": len(samples), "samples": samples}


@app.post("/api/sim/gold")
async def post_gold_samples(request: Request):
    data = await request.json()
    samples = data.get("samples")
    if not isinstance(samples, list):
        raise HTTPException(400, "samples 必须为数组")
    try:
        out = gold.set_gold(samples)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"count": len(out), "samples": out}


@app.post("/api/sim/schedule")
async def post_schedule(request: Request):
    # 稳健解析请求体：空 body / 非 JSON / 非对象 时均回退为 {}，
    # 避免空 POST（如 `curl -X POST .../schedule`）触发 JSONDecodeError 而 500
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    if not isinstance(data, dict):
        data = {}
    use_llm = bool(data.get("use_llm", False))
    backend = data.get("backend")
    try:
        result = simulator.run_schedule_sim(backend_name=backend, use_llm=use_llm)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"调度模拟失败：{e}")
    return result


# ============================ F2 成本/延迟仿真 ============================

@app.get("/api/sim/pricing")
def get_pricing():
    return pricing.get_pricing()


@app.put("/api/sim/pricing")
async def put_pricing(request: Request):
    data = await request.json()
    models = data.get("models")
    if not isinstance(models, list) or not models:
        raise HTTPException(400, "models 必须为非空数组")
    out = pricing.save_pricing(models)
    return {"models": out["models"], "as_of": out["as_of"], "disclaimer": out["disclaimer"]}


@app.post("/api/sim/cost")
async def post_cost(request: Request):
    data = await request.json()
    model = data.get("model")
    if not model:
        raise HTTPException(400, "缺少 model")
    try:
        skills_count = int(data.get("skills_count", 0) or 0)
        turns = int(data.get("turns", 0) or 0)
        rb = int(data.get("resident_tokens_before", 0) or 0)
        ra = data.get("resident_tokens_after")
        ra = int(ra) if ra is not None else None
    except (TypeError, ValueError):
        raise HTTPException(400, "参数必须为整数")
    if turns <= 0 or rb < 0:
        raise HTTPException(400, "turns 必须 > 0，resident_tokens_before 必须 ≥ 0")
    try:
        result = simulator.run_cost_sim(model, skills_count, turns, rb, ra)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


# ============================ F3 语义冲突检测 ============================

@app.get("/api/conflicts")
def get_conflicts(threshold: float = config.CONFLICT_DEFAULT_THRESHOLD):
    try:
        return simulator.detect_conflicts(threshold=threshold)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"冲突检测失败：{e}")


# ============================ 闭环：规则沉淀 / 后端配置 / 预算回调 ============================

@app.put("/api/rules/custom")
async def put_custom_rule(request: Request):
    data = await request.json()
    kc = data.get("keyword_cluster")
    suggestion = data.get("suggestion", "")
    rule = data.get("rule")
    severity = data.get("severity", "warning")
    if not isinstance(kc, list) or not kc:
        raise HTTPException(400, "keyword_cluster 必须为非空数组")
    try:
        obj = custom_rules.deposit_custom_rule(kc, suggestion, rule, severity)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"rule": obj}


@app.get("/api/config/vectorizer")
def get_vectorizer_config():
    v = get_vectorizer()
    name = "embedding" if v.__class__.__name__ == "EmbeddingBackend" else "local-tfidf"
    cfg = _load_vectorizer_config()
    emb = cfg.get("embedding", {})
    return {
        "backend": name,
        "embedding": {
            "api_url": emb.get("api_url", ""),
            "api_key_env": emb.get("api_key_env", "EMBEDDING_API_KEY"),
            "model": emb.get("model", "text-embedding-3-small"),
        },
    }


@app.put("/api/config/vectorizer")
async def put_vectorizer_config(request: Request):
    data = await request.json()
    backend = data.get("backend")
    if backend not in ("local-tfidf", "embedding"):
        raise HTTPException(400, "backend 必须为 local-tfidf 或 embedding")
    emb = data.get("embedding") or {}
    cfg = {
        "backend": backend,
        "embedding": {
            "api_url": emb.get("api_url", ""),
            "api_key_env": emb.get("api_key_env", "EMBEDDING_API_KEY"),
            "model": emb.get("model", "text-embedding-3-small"),
        },
    }
    # embedding 未配 api_url 时回退 local-tfidf，并给出告警提示
    warn = None
    if backend == "embedding" and not cfg["embedding"]["api_url"]:
        cfg["backend"] = "local-tfidf"
        warn = "embedding 未配置 api_url，已回退 local-tfidf"
    config.VECTORIZER_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    resp = {
        "backend": cfg["backend"],
        "embedding": cfg["embedding"],
    }
    if warn:
        resp["warning"] = warn
    return resp


@app.put("/api/sim/budget")
async def put_sim_budget(request: Request):
    data = await request.json()
    skill_id = data.get("skill_id")
    if not skill_id:
        raise HTTPException(400, "缺少 skill_id")
    target = data.get("target")
    target = int(target) if target is not None else None
    try:
        entry = budget.manual_recall(skill_id, target)
    except (TypeError, ValueError):
        raise HTTPException(400, "target 必须为整数")
    return {
        "skill_id": skill_id,
        "target": entry["target"],
        "regress_count": entry.get("regress_count", 0),
    }


@app.get("/api/sim/trends")
def get_sim_trends():
    return {
        "schedule": simbank.get_schedule_trend(),
        "cost": simbank.get_cost_trend(),
    }


# ---- 静态前端 ----
@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
