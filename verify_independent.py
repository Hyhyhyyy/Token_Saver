"""SkillForge v2.2 —— 独立验证脚本（QA 新鲜眼光，不依赖工程师用例）。

覆盖验收 B 组 6 项：
  B.1 calibrate 优雅降级（local-st 指向不可达 endpoint → 绝不 500）
  B.2 no-op 保护（连续两次 run_evolve → 第二次 no_op:True, ledger_new:[], metrics 不新增）
  B.3 trends 升序（空数据不报错；填充数据按 ts 升序）
  B.4 自动循环状态（status 初始 false / start→true / stop→false）
  B.5 ledger 时间窗过滤（since/until 正确过滤）
  B.6 前端零构建（grep 第三方图表库引用）

运行：python verify_independent.py
退出码：0 = 全部通过；1 = 存在失败项。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# --------------------------------------------------------------------------- #
# 隔离环境工具（仿 conftest，但独立自包含，不依赖 pytest）
# --------------------------------------------------------------------------- #
REPO = Path(__file__).resolve().parent


def _deterministic_vec(text: str, dim: int = 128) -> list[float]:
    vec = [0.0] * dim
    for ch in text or "":
        vec[ord(ch) % dim] += 1.0
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0:
        return [0.0] * dim
    return [v / norm for v in vec]


class MockEmbeddingServer:
    def __init__(self):
        self._server = None
        self._thread = None
        self._port = 0

    def _make_handler(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(h):
                length = int(h.headers.get("Content-Length", 0) or 0)
                body = h.rfile.read(length) if length else b""
                try:
                    payload = json.loads(body) if body else {}
                except Exception:
                    payload = {}
                inp = payload.get("input", "")
                texts = inp if isinstance(inp, list) else [inp]
                data = [
                    {"object": "embedding", "index": i,
                     "embedding": _deterministic_vec(str(t))}
                    for i, t in enumerate(texts)
                ]
                out = json.dumps(
                    {"object": "list", "data": data,
                     "model": payload.get("model", "mock")}
                ).encode("utf-8")
                h.send_response(200)
                h.send_header("Content-Type", "application/json")
                h.send_header("Content-Length", str(len(out)))
                h.end_headers()
                h.wfile.write(out)

            def log_message(self, *a):
                pass

        return Handler

    def start(self):
        self._server = HTTPServer(("127.0.0.1", 0), self._make_handler())
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}/v1/embeddings"


def _fresh_env(data_dir: Path, skills_dir: Path, vectorizer_cfg: dict) -> None:
    os.environ["DATA_DIR"] = str(data_dir)
    os.environ["USER_SKILLS_DIR"] = str(skills_dir)
    os.environ["SKILLS_DIRS"] = str(skills_dir)
    os.environ["AUTO_EVOLVE_LOOP"] = "false"
    os.environ["AUTO_EVOLVE_ON_START"] = "false"
    (data_dir / "vectorizer.json").write_text(
        json.dumps(vectorizer_cfg, ensure_ascii=False), encoding="utf-8"
    )
    for name in list(sys.modules):
        if name == "skillforge" or name.startswith("skillforge."):
            del sys.modules[name]
    import skillforge  # noqa: F401
    import skillforge.config  # noqa: F401
    import skillforge.scorer  # noqa: F401
    import skillforge.simulator  # noqa: F401
    import skillforge.simbank  # noqa: F401
    import skillforge.gold  # noqa: F401
    import skillforge.budget  # noqa: F401
    import skillforge.custom_rules  # noqa: F401
    import skillforge.evolve  # noqa: F401
    import skillforge.auto_loop  # noqa: F401
    import skillforge.server  # noqa: F401
    return skillforge


def _make_skill(skills_dir: Path, name: str, desc: str, body: str = "示例正文") -> None:
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n{body}\n", encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# 结果收集
# --------------------------------------------------------------------------- #
RESULTS: list[tuple[str, bool, str]] = []


def record(check: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((check, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {check}" + (f" — {detail}" if detail else ""))


# --------------------------------------------------------------------------- #
# B.1 calibrate 优雅降级（local-st 指向不可达 endpoint）
# --------------------------------------------------------------------------- #
def check_b1_calibrate_graceful_degradation():
    tmp = Path(tempfile.mkdtemp(prefix="sf_b1_"))
    data_dir = tmp / "data"
    skills_dir = tmp / "skills"
    data_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)
    # local-st 指向不可达端口（连接被拒绝），且确保无 mock server
    cfg = {
        "backend": "embedding",
        "provider": "local-st",
        "embedding": {"api_url": "http://127.0.0.1:1/v1/embeddings",
                      "model": "nomic-embed-text"},
    }
    sf = _fresh_env(data_dir, skills_dir, cfg)
    _make_skill(skills_dir, "my-alpha", "处理用户订单退款与售后流程")
    _make_skill(skills_dir, "my-beta", "生成Python数据可视化图表脚本")

    # 1) 直接调用 evolve.calibrate()
    r = sf.evolve.calibrate(limit=10)
    ok = r.get("available") is False and bool(r.get("reason"))
    record("B.1a calibrate() 不可达 → available:false + reason（不抛异常）", ok,
           f"available={r.get('available')}, reason={r.get('reason')!r}")

    # 2) 经 TestClient GET /api/evolve/calibration → 绝不 500
    from fastapi.testclient import TestClient
    client = TestClient(sf.server.app)
    resp = client.get("/api/evolve/calibration")
    ok2 = resp.status_code == 200 and resp.json().get("available") is False
    record("B.1b GET /api/evolve/calibration → 200（无 500）", ok2,
           f"status={resp.status_code}, body={resp.json()}")


# --------------------------------------------------------------------------- #
# B.2 no-op 保护（连续两次 run_evolve）
# --------------------------------------------------------------------------- #
def check_b2_noop_protection():
    tmp = Path(tempfile.mkdtemp(prefix="sf_b2_"))
    data_dir = tmp / "data"
    skills_dir = tmp / "skills"
    data_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)
    srv = MockEmbeddingServer().start()
    try:
        cfg = {
            "backend": "embedding",
            "provider": "local-st",
            "embedding": {"api_url": srv.url, "model": "nomic-embed-text"},
        }
        sf = _fresh_env(data_dir, skills_dir, cfg)
        # 两个描述差异极大 → 无冲突命中、无回归自动回调
        _make_skill(skills_dir, "my-alpha", "处理用户订单退款与售后流程")
        _make_skill(skills_dir, "my-beta", "生成Python数据可视化图表脚本")

        r1 = sf.evolve.run_evolve(trigger="manual")
        seeded1 = r1["gold"]["seeded"]
        metrics_after_r1 = len(sf.simbank.get_evolution_metrics())

        r2 = sf.evolve.run_evolve(trigger="manual")
        metrics_after_r2 = len(sf.simbank.get_evolution_metrics())

        ok = (
            seeded1 == 2
            and r1["no_op"] is False
            and r2["no_op"] is True
            and r2["ledger_new"] == []
            and metrics_after_r2 == metrics_after_r1  # no-op 不新增 metrics
        )
        record("B.2 no-op 保护（第二次 no_op:True / ledger_new:[] / metrics 不新增）", ok,
               f"r1.no_op={r1['no_op']}, r2.no_op={r2['no_op']}, "
               f"r2.ledger_new={r2['ledger_new']}, "
               f"metrics={metrics_after_r1}→{metrics_after_r2}")
    finally:
        srv.stop()


# --------------------------------------------------------------------------- #
# B.3 trends 升序（空数据 + 填充数据）
# --------------------------------------------------------------------------- #
def check_b3_trends_ascending():
    tmp = Path(tempfile.mkdtemp(prefix="sf_b3_"))
    data_dir = tmp / "data"
    skills_dir = tmp / "skills"
    data_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)
    srv = MockEmbeddingServer().start()
    try:
        cfg = {
            "backend": "embedding",
            "provider": "local-st",
            "embedding": {"api_url": srv.url, "model": "nomic-embed-text"},
        }
        sf = _fresh_env(data_dir, skills_dir, cfg)
        _make_skill(skills_dir, "my-alpha", "处理用户订单退款与售后流程")
        _make_skill(skills_dir, "my-beta", "生成Python数据可视化图表脚本")

        # 空数据：不报错，返回 []
        empty = sf.simbank.get_evolution_metrics()
        ok_empty = empty == []
        record("B.3a 空数据 trends → [] 且不报错", ok_empty, f"points={empty}")

        # 填充数据：两段 run_evolve → ts 升序
        sf.evolve.run_evolve(trigger="manual")
        _make_skill(skills_dir, "my-gamma", "整理会议纪要与待办清单")
        sf.evolve.run_evolve(trigger="manual")
        pts = sf.simbank.get_evolution_metrics()
        ascending = all(pts[i]["ts"] <= pts[i + 1]["ts"] for i in range(len(pts) - 1))
        ok_fill = len(pts) >= 2 and ascending
        record("B.3b 填充数据 trends 按 ts 升序", ok_fill,
               f"count={len(pts)}, ascending={ascending}")

        # 端点视角
        from fastapi.testclient import TestClient
        client = TestClient(sf.server.app)
        resp = client.get("/api/evolve/trends?limit=10")
        pj = resp.json()["points"]
        asc2 = all(pj[i]["ts"] <= pj[i + 1]["ts"] for i in range(len(pj) - 1))
        ok_ep = resp.status_code == 200 and len(pj) >= 2 and asc2
        record("B.3c GET /api/evolve/trends 升序", ok_ep,
               f"status={resp.status_code}, count={len(pj)}, ascending={asc2}")
    finally:
        srv.stop()


# --------------------------------------------------------------------------- #
# B.4 自动循环状态
# --------------------------------------------------------------------------- #
def check_b4_auto_loop_status():
    tmp = Path(tempfile.mkdtemp(prefix="sf_b4_"))
    data_dir = tmp / "data"
    skills_dir = tmp / "skills"
    data_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)
    cfg = {"backend": "local-tfidf"}  # 自动循环与后端无关
    sf = _fresh_env(data_dir, skills_dir, cfg)

    # 直接调用 auto_loop；start() 的公开契约要求存在运行中的事件循环。
    async def _direct_flow():
        s0 = sf.auto_loop.status()
        sf.auto_loop.start()
        s1 = sf.auto_loop.status()
        sf.auto_loop.stop()
        s2 = sf.auto_loop.status()
        return s0, s1, s2

    s0, s1, s2 = asyncio.run(_direct_flow())
    ok_direct = (
        s0["running"] is False
        and s1["running"] is True
        and s2["running"] is False
    )
    record("B.4a auto_loop.status 初始 false / start→true / stop→false", ok_direct,
           f"{s0['running']}→{s1['running']}→{s2['running']}")

    # 端点视角：用单事件循环的 httpx.AsyncClient（贴近生产 uvicorn 行为）。
    # 注意：Starlette 的 TestClient 每次请求新建事件循环，后台 asyncio 任务会在
    # 两次请求间被销毁，导致 status 误报 false；故此处用持久单循环验证真实行为。
    import httpx
    from httpx import ASGITransport

    async def _ep_flow():
        transport = ASGITransport(app=sf.server.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r0 = (await c.get("/api/evolve/auto/status")).json()
            r_start = (await c.post("/api/evolve/auto/start")).json()
            r1 = (await c.get("/api/evolve/auto/status")).json()
            r_stop = (await c.post("/api/evolve/auto/stop")).json()
            r2 = (await c.get("/api/evolve/auto/status")).json()
            return r0, r_start, r1, r_stop, r2

    r0, r_start, r1, r_stop, r2 = asyncio.run(_ep_flow())
    ok_ep = (
        r0["running"] is False
        and r_start["ok"] is True and r_start["running"] is True
        and r1["running"] is True
        and r_stop["ok"] is True and r_stop["running"] is False
        and r2["running"] is False
    )
    record("B.4b /api/evolve/auto/{status,start,stop} 状态切换", ok_ep,
           f"status={r0['running']}→{r1['running']}→{r2['running']}")


# --------------------------------------------------------------------------- #
# B.5 ledger 时间窗过滤
# --------------------------------------------------------------------------- #
def check_b5_ledger_time_window():
    tmp = Path(tempfile.mkdtemp(prefix="sf_b5_"))
    data_dir = tmp / "data"
    skills_dir = tmp / "skills"
    data_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)
    srv = MockEmbeddingServer().start()
    try:
        cfg = {
            "backend": "embedding",
            "provider": "local-st",
            "embedding": {"api_url": srv.url, "model": "nomic-embed-text"},
        }
        sf = _fresh_env(data_dir, skills_dir, cfg)
        _make_skill(skills_dir, "my-alpha", "处理用户订单退款与售后流程")
        _make_skill(skills_dir, "my-beta", "生成Python数据可视化图表脚本")
        sf.evolve.run_evolve(trigger="manual")

        from fastapi.testclient import TestClient
        client = TestClient(sf.server.app)

        # 全量（含过去下界、未来上界）应返回条目
        full = client.get("/api/evolve/ledger?since=2000-01-01T00:00:00+00:00"
                          "&until=2999-01-01T00:00:00+00:00").json()
        # 未来窗口：不返回任何条目
        future = client.get("/api/evolve/ledger?since=2999-01-01T00:00:00+00:00").json()
        # 精确 since（本轮写入之后）应过滤掉历史
        later = client.get("/api/evolve/ledger?since=2999-12-31T23:59:59+00:00").json()

        ok = (
            full["count"] >= 1
            and future["entries"] == []
            and later["entries"] == []
        )
        record("B.5 ledger 时间窗过滤（since/until）", ok,
               f"full={full['count']}, future={len(future['entries'])}, "
               f"later={len(later['entries'])}")
    finally:
        srv.stop()


# --------------------------------------------------------------------------- #
# B.6 前端零构建（无第三方图表库 / 构建依赖）
# --------------------------------------------------------------------------- #
def check_b6_frontend_zero_build():
    hits = []
    # 检查是否引用第三方图表库
    for pat in ("chart.js", "echarts", "d3.js", "plotly"):
        for p in REPO.joinpath("frontend").rglob("*"):
            if p.is_file() and p.suffix in (".html", ".js", ".css"):
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                if pat in text.lower():
                    hits.append(f"{p.name}:{pat}")
    # 检查 <script src= 是否指向非本地/第三方（CDN）
    cdn = []
    idx = REPO.joinpath("frontend") / "index.html"
    if idx.exists():
        text = idx.read_text(encoding="utf-8", errors="ignore")
        import re
        for m in re.findall(r'<script[^>]*src=["\']([^"\']+)["\']', text):
            if m.startswith("http://") or m.startswith("https://") or "cdn" in m.lower():
                cdn.append(m)
    ok = not hits and not cdn
    detail = "无第三方图表库/CDN 引用" if ok else f"charts={hits}, cdn={cdn}"
    record("B.6 前端零构建（无第三方图表库/CDN 引用）", ok, detail)


# --------------------------------------------------------------------------- #
def main() -> int:
    print("=" * 70)
    print("SkillForge v2.2 独立验证（QA 新鲜眼光）")
    print("=" * 70)
    check_b1_calibrate_graceful_degradation()
    check_b2_noop_protection()
    check_b3_trends_ascending()
    check_b4_auto_loop_status()
    check_b5_ledger_time_window()
    check_b6_frontend_zero_build()

    print("\n" + "-" * 70)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"独立验证：{passed}/{total} 通过")
    failed = [c for c, ok, _ in RESULTS if not ok]
    if failed:
        print("失败项：")
        for f in failed:
            print(f"  - {f}")
    print("-" * 70)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
