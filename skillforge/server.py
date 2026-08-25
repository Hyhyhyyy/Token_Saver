"""FastAPI 服务：暴露 REST API 并托管前端静态资源。"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .skill_parser import scan_skills, get_skill_by_id
from .validator import validate
from .cleaner import clean_skill
from .tracker import log_event, get_stats, get_series, get_leaderboard, get_skill_stats
from .tokenizer import BACKEND, count_tokens
from .prompt_simplifier import simplify_prompt
from .spec import STANDARD_VERSION, SKILL_TEMPLATE, DESC_TEMPLATE, DESC_EXAMPLE, get_validation_rules
from . import config
from . import budget, gold, pricing, custom_rules, simulator, simbank, evolve, auto_loop, skill_signature
from . import personal
from .personal import load_personal_phrases, add_personal_phrase, remove_personal_phrase
from .scorer import get_vectorizer, _load_vectorizer_config, conflict_default_threshold
from .scorer import (
    resolve_backend_source,
    get_ollama_available,
    set_ollama_available,
    ensure_default_vectorizer,
    probe_ollama,
    probe_candidates,
)
import json
from urllib.parse import urlsplit

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

@asynccontextmanager
async def lifespan(app: FastAPI):
    """开机自启 Hook（E5，受 AUTO_EVOLVE_ON_START / AUTO_EVOLVE_LOOP 开关控制，默认 false）。

    - AUTO_EVOLVE_ON_START=true：保留 v2.1 开机钩子（bootstrap_gold → 调度模拟 →
      自动回调），其内部逻辑经 auto_loop.run_protected 进入（互斥锁保护）。
    - AUTO_EVOLVE_LOOP=true：启动进程内后台周期自动循环（默认 false，绝不静默写盘）。
    任何异常吞掉仅记录，绝不影响应用就绪；两个开关默认均 false。

    D-2：启动时探测 ollama 可用性并据预设落地 DATA_DIR/vectorizer.json（开箱即用），
    结果缓存于 scorer 模块级变量，仅启动/lifespan 探测一次（Q8）。
    """
    # D-2 / D-3：启动按序探测多本地候选 embeddings 端点 + 落地默认 vectorizer.json
    try:
        winner = probe_candidates(config.EMBEDDING_CANDIDATE_URLS)
        if winner:
            # 胜出端点可用 → 缓存可用 + 落地 local-st（api_url=胜出端点，U3）
            set_ollama_available(True)
            ensure_default_vectorizer(candidate_url=winner)
        else:
            # 全不可达 → 回退 local-tfidf（与 D-2 一致）
            set_ollama_available(False)
            ensure_default_vectorizer()
    except Exception as e:  # noqa: BLE001
        print(f"[evolve] 后端探测/落地 vectorizer 异常（已吞掉）：{e}")

    if config.auto_evolve_on_start():
        try:
            def _boot_sequence():
                evolve.bootstrap_gold(force=True, trigger="startup")
                before = budget.load_overrides()
                simulator.run_schedule_sim()
                after = budget.load_overrides()
                evolve._capture_auto_recall(before, after, "startup")

            await auto_loop.run_protected(_boot_sequence)
        except Exception as e:  # noqa: BLE001
            print(f"[evolve] 开机自启异常（已吞掉，不影响启动）：{e}")

    if config.auto_evolve_loop():
        auto_loop.start()

    yield

    # 关机：停止自动循环（释放后台任务）
    try:
        auto_loop.stop()
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(title="SkillForge · 技能精炼台", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def local_security_boundary(request: Request, call_next):
    """Reject browser cross-site writes and oversized request bodies.

    SkillForge intentionally has no remote-user authentication and must remain a
    loopback-only tool. This middleware blocks drive-by browser requests while
    preserving CLI/TestClient use where the Origin header is absent.
    """
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 1_048_576:
                return Response("request body too large", status_code=413)
        except ValueError:
            return Response("invalid content-length", status_code=400)

    origin = request.headers.get("origin")
    if origin and request.method not in {"GET", "HEAD", "OPTIONS"}:
        parsed = urlsplit(origin)
        expected_host = request.headers.get("host", "")
        if parsed.scheme not in {"http", "https"} or parsed.netloc != expected_host:
            return Response("cross-origin write rejected", status_code=403)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'"
    )
    return response


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
            "path": f"{s['dir_name']}/SKILL.md",
            "desc_tokens": s["desc_tokens"],
            "total_tokens": s["total_tokens"],
            "status": v["status"],
            "score": v["score"],
            "error_count": v["error_count"],
            "warning_count": v["warning_count"],
            "info_count": v["info_count"],
            "parse_error": "skill metadata could not be parsed" if s.get("parse_error") else None,
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
        "path": f"{s['dir_name']}/SKILL.md",
        "frontmatter": s["frontmatter"],
        "body": s["body"],
        "body_raw": s["body_raw"],
        "desc_tokens": s["desc_tokens"],
        "total_tokens": s["total_tokens"],
        "validation": v,
        "parse_error": "skill metadata could not be parsed" if s.get("parse_error") else None,
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
    # CWE-377 修复：弃用 tempfile.mktemp（存在竞态/预测风险），改为
    # NamedTemporaryFile(delete=False) 并在 finally 中确保删除临时文件。
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(serialized)
            tmp = Path(fh.name)
        from .skill_parser import parse_skill_file, description_tokens
        parsed = parse_skill_file(tmp)
    finally:
        # 无论解析成功/失败/异常，均清理临时文件（避免残留 .md 泄漏）
        if tmp is not None and tmp.exists():
            try:
                tmp.unlink()
            except OSError:  # noqa: BLE001
                pass
    fm = parsed.get("frontmatter", {})
    if not fm.get("name") or not str(fm.get("description", "")).strip():
        raise HTTPException(400, "清洗结果缺少 name 或 description，已拒绝写入以防损坏")
    if parsed.get("parse_error"):
        raise HTTPException(400, "清洗结果无法解析")

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


# ============================ v2.5 Prompt 简化器（核心新功能） ============================

@app.post("/api/simplify")
async def simplify(request: Request) -> dict:
    """Prompt 简化器：粘贴/拖拽的 prompt 文本 → 压缩 + token 节省统计。

    请求体 {text, mode?}，mode 默认 "balanced"，可选 "aggressive"。
    空 text 优雅返回全零/空串（original_text="" / simplified_text="" / 各计数 0 /
    changes=[]），不会 500。
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    text = body.get("text", "")
    mode = body.get("mode", "balanced")
    # v2.6：可选 rules（类别多选）。非 list 一律兜底 None → 走 PRESETS（P0-3 零回归）。
    # evo2-7 契约：rules=None 时后端 explicit=False，仅 5 基础类且逐字等于 v2.5；
    # 新类别 logical_connector / filler_particles 永不进 PRESETS，仅当用户显式下发
    # rules（非空 list）时生效（explicit=True）。本分支无逻辑改动。
    rules = body.get("rules", None)
    if not isinstance(rules, list):
        rules = None
    # evo2-9：可选语义压缩参数（缺省/非法静默回落默认，绝不 500）
    semantic_threshold = body.get("semantic_threshold", None)
    semantic_prune = body.get("semantic_prune", False)
    if not isinstance(semantic_prune, bool):
        semantic_prune = False
    # 个性化口癖：默认开启（apply_personal 缺省 True）；关闭则跳过。
    apply_personal = body.get("apply_personal", True)
    if not isinstance(apply_personal, bool):
        apply_personal = True
    personal = load_personal_phrases() if apply_personal else []
    return simplify_prompt(
        text, mode=mode, rules=rules,
        semantic_threshold=semantic_threshold, semantic_prune=semantic_prune,
        personal_phrases=personal if personal else None,
    )


# ============================ 个性化口癖（v2.14 新功能） ============================

@app.get("/api/personal/phrases")
def get_personal_phrases() -> dict:
    """读取个性化口癖清单。"""
    return {"phrases": load_personal_phrases()}


@app.post("/api/personal/phrases")
async def post_personal_phrase(request: Request) -> dict:
    """新增一条口癖（自动 trim / 去重）。返回最新清单与是否新增。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    phrases, added = add_personal_phrase(str(body.get("phrase", "")))
    return {"phrases": phrases, "added": added}


@app.delete("/api/personal/phrases")
async def delete_personal_phrase(request: Request) -> dict:
    """删除一条口癖（按精确匹配）。返回最新清单。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    if not isinstance(body, dict):
        body = {}
    phrases = remove_personal_phrase(str(body.get("phrase", "")))
    return {"phrases": phrases}


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


# ============================ 仿真沙盘已移除（v2.14） ============================
# 原 F1 调度反事实模拟 / F2 成本延迟仿真 路由（/api/sim/gold|schedule|pricing|cost）
# 已删除；冲突检测（F3）保留于下方 /api/conflicts。


# ============================ F3 语义冲突检测 ============================

@app.get("/api/conflicts")
def get_conflicts(threshold: float | None = None):
    try:
        t = threshold if threshold is not None else conflict_default_threshold()
        return simulator.detect_conflicts(threshold=t)
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
    # 落点补记账本（E1）：手动沉淀冲突规则（去重命中时不重复记，避免账本膨胀）
    if obj.get("deposited", True):
        simbank.log_evolution(
            "conflict_rule_deposit", obj["id"], "",
            json.dumps(obj.get("keyword_cluster", []), ensure_ascii=False),
            "manual", "手动沉淀冲突规则",
        )
    return {"rule": obj, "deposited": obj.get("deposited", True)}


@app.get("/api/config/vectorizer")
def get_vectorizer_config():
    v = get_vectorizer()
    name = "embedding" if v.__class__.__name__ == "EmbeddingBackend" else "local-tfidf"
    cfg = _load_vectorizer_config()
    emb = cfg.get("embedding", {})
    provider = cfg.get("provider")
    if provider is None:
        provider = "openai" if cfg.get("backend") == "embedding" else "local-tfidf"
    src = resolve_backend_source()
    return {
        "backend": name,
        "provider": provider,
        "backend_source": src["backend_source"],
        "ollama_available": src["ollama_available"],
        "embedding": {
            "api_url": emb.get("api_url", ""),
            "api_key_env": emb.get("api_key_env", "EMBEDDING_API_KEY"),
            "model": emb.get("model", "text-embedding-3-small"),
        },
    }


@app.post("/api/config/vectorizer/probe")
def post_probe_vectorizer():
    """显式刷新多候选 embeddings 端点探测 + 落地默认 vectorizer.json + 返回当前后端来源（Q8）。

    不每次 run_evolve 探测，仅在启动/lifespan 与「显式刷新」时重新探测并缓存（D-3）。
    """
    try:
        winner = probe_candidates(config.EMBEDDING_CANDIDATE_URLS)
        if winner:
            set_ollama_available(True)
            ensure_default_vectorizer(candidate_url=winner)
        else:
            set_ollama_available(False)
            ensure_default_vectorizer()
        return resolve_backend_source()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"vectorizer 探测失败：{e}")


@app.put("/api/config/vectorizer")
async def put_vectorizer_config(request: Request):
    data = await request.json()
    backend = data.get("backend")
    if backend not in ("local-tfidf", "embedding"):
        raise HTTPException(400, "backend 必须为 local-tfidf 或 embedding")
    if backend == "embedding":
        provider = data.get("provider") or "openai"
    else:
        provider = "local-tfidf"
    emb = data.get("embedding") or {}
    cfg = {
        "backend": backend,
        "provider": provider,
        "embedding": {
            "api_url": emb.get("api_url", ""),
            "api_key_env": emb.get("api_key_env", "EMBEDDING_API_KEY"),
            "model": emb.get("model", "text-embedding-3-small"),
        },
    }
    # embedding 未配 api_url 且非 local-st（本地默认端点可用）时回退 local-tfidf
    warn = None
    if backend == "embedding" and provider != "local-st" and not cfg["embedding"]["api_url"]:
        cfg["backend"] = "local-tfidf"
        cfg["provider"] = "local-tfidf"
        warn = "embedding 未配置 api_url，已回退 local-tfidf"
    config.VECTORIZER_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    resp = {
        "backend": cfg["backend"],
        "provider": cfg["provider"],
        "embedding": cfg["embedding"],
    }
    if warn:
        resp["warning"] = warn
    return resp


# ============================ 仿真沙盘预算/趋势路由已移除（v2.14） ============================
# 原 /api/sim/budget、/api/sim/trends 已删除（仿真沙盘整体下线）。


# ============================ 自进化引擎（v2.1 · 进化账本 / 自主进化） ============================

@app.get("/api/evolve/pressure")
def get_evolve_pressure() -> dict:
    """A-4 压力源信号可观测：返回最近一次 `skill_signature_change` 账本条目的解析
    changeset（added/removed/changed 名称）+ 时间，以及当前签名统计（技能数/基线路径）。

    - 读 simbank.get_ledger(action_type="skill_signature_change", limit=1) 取最新一条；
      解析其 after_val（JSON changeset）+ ts。
    - 无历史变化时 last_change 为 null。
    - 零新增存储：直接复用 evolution_ledger，不改存储结构。
    """
    ledger = simbank.get_ledger(action_type="skill_signature_change", limit=1)
    last_change = None
    if ledger.get("entries"):
        entry = ledger["entries"][0]
        try:
            changeset = json.loads(entry["after_val"]) if entry.get("after_val") else {}
        except Exception:
            changeset = {}
        if not isinstance(changeset, dict):
            changeset = {}
        last_change = {
            "added": changeset.get("added", []) or [],
            "removed": changeset.get("removed", []) or [],
            "changed": changeset.get("changed", []) or [],
            "ts": entry.get("ts"),
        }
    sigs = skill_signature.compute_signatures()
    return {
        "last_change": last_change,
        "signature": {
            "skill_count": len(sigs),
            "baseline": "skills_signature.json",
        },
    }


@app.get("/api/evolve/ledger")
def get_evolve_ledger(limit: int = 50, action_type: str | None = None,
                      object: str | None = None,
                      since: str | None = None, until: str | None = None):
    """分页 + 过滤查询进化账本（C-2：新增 since/until 时间窗过滤）。limit 夹紧 [1,200]。"""
    lim = max(1, min(200, int(limit)))
    return simbank.get_ledger(limit=lim, action_type=action_type, object=object,
                              since=since, until=until)


@app.get("/api/evolve/trends")
def get_evolve_trends(limit: int = 100):
    """进化趋势采集点（C-1）：每次 run_evolve 写一行覆盖度 / F1 选对率，按 ts 升序。"""
    return {"points": simbank.get_evolution_metrics(limit)}


@app.get("/api/evolve/report")
def get_evolve_report(format: str = "markdown", since: str | None = None, until: str | None = None):
    """导出进化报告。format=markdown 返回 text/markdown 字符串（前端 Blob 下载）；
    format=json 返回 {generated_at, summary, entries}。since/until 支持时间窗（P1-3）。"""
    if format not in ("markdown", "json"):
        format = "markdown"
    result = simbank.build_report(format=format, since=since, until=until)
    if format == "json":
        return result
    return Response(content=result, media_type="text/markdown; charset=utf-8")


@app.post("/api/evolve/bootstrap-gold")
async def post_bootstrap_gold(request: Request):
    """播种用户真实技能的 gold 样本（GOAL-1 真实信号）。可选 {force?}。"""
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    if not isinstance(data, dict):
        data = {}
    force = bool(data.get("force", False))
    return evolve.bootstrap_gold(force=force, trigger="auto_bootstrap")


@app.get("/api/evolve/calibration")
def get_calibration(limit: int = config.CALIBRATION_SAMPLE_PAIRS):
    """校准：local-tfidf vs embedding 打分对比（E3）。未配 embedding 返回 {available:false}（200）。"""
    return evolve.calibrate(limit=limit)


@app.post("/api/evolve/run")
async def post_evolve_run(request: Request):
    """运行自主进化引擎（E4）：播种 → 调度模拟 → 冲突沉淀 → 写账本。

    经 auto_loop.run_protected 进入（互斥锁保护，手动/自动/开机三路同一时刻仅一个
    run_evolve 在跑）。可选 {seed_threshold?}。返回结果含 no_op 字段（B-3）。
    """
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        data = {}
    if not isinstance(data, dict):
        data = {}
    seed_threshold = data.get("seed_threshold")
    seed_threshold = int(seed_threshold) if isinstance(seed_threshold, int) else None

    def _run():
        return evolve.run_evolve(seed_threshold=seed_threshold, trigger="manual")

    try:
        return await auto_loop.run_protected(_run)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"自主进化失败：{e}")


@app.get("/api/evolve/auto/status")
def get_auto_status():
    """自动循环状态（B-2）：running / last_run / next_run_in_sec / interval_min。"""
    return auto_loop.status()


@app.post("/api/evolve/auto/start")
async def post_auto_start():
    """启动后台周期自动循环（B-2，幂等）。"""
    auto_loop.start()
    return {"ok": True, "running": True, "interval_min": auto_loop.status()["interval_min"]}


@app.post("/api/evolve/auto/stop")
async def post_auto_stop():
    """停止后台周期自动循环（B-2）。"""
    auto_loop.stop()
    return {"ok": True, "running": False}


# ---- 静态前端 ----
@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
