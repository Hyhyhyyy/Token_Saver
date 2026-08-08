# SkillForge v2.2 交付报告（真实信号落地 + 全自动闭环 + 进化可视化）

> 交付日期：2026-08-07　|　团队：`software-skillforge-evo3`（主理人 齐活林 / PM 许清楚 / 架构 高见远 / 工程 寇豆码 / QA 严过关）
> 代码库：`C:\Users\lenovo\WorkBuddy\2026.9黑客松\skill-forge`（远程 `Hyhyhyyy/Token_Saver`，仅用户本人贡献）
> 版本：`__version__ = "2.2.0-evo"`　|　远程 tip：`85963c4`（fast-forward 自 `01c0eac`，author=Hyhyhyyy）

---

## 1. TL;DR
在 v2.1「自主进化引擎 + 进化账本」之上，增量升级为 **真实 embedding 信号生效 / 全自动闭环 / 进化可视化可观测 / 全量回归可验证**。四个用户选定方向（A 真实 embedding 接入 / B 自进化自动化 / C 前端进化视图增强 / D 文档 + 全量回归）全部交付，QA 验收 **18/18 pytest + 10/10 独立验证全绿，源码零 bug**。

---

## 2. 交付概览

| 维度 | 结果 |
|------|------|
| 测试通过率 | **全量回归 18/18** + 独立验证 **10/10**（共 28 项） |
| 源码 Bug | **0**（发现的问题均来自测试隔离，由 QA 自修） |
| 已知问题 | 2 项非阻塞（见 §6） |
| 新增依赖 | **零新增 pip 依赖**（严守 v2.1 约束） |
| 前端构建 | **零构建**（趋势图手写 SVG，无第三方图表库） |
| 提交/推送 | 本地 `2bb3615` + `85963c4`，已 `git push origin main`（fast-forward，历史仅 Hyhyhyyy） |
| 线上实例 | http://127.0.0.1:8008 已重启加载 v2.2，新端点全部 200 |

---

## 3. 四个方向交付内容

### A · 真实 embedding 接入
- `scorer.py`：`_VECTORIZER_REGISTRY` + `register_vectorizer`（P1 插件钩子）；`get_vectorizer(backend_name, provider)` 支持 `openai` / `local-st` 两种 provider（`local-st` = `EmbeddingBackend` 指向本地 OpenAI 兼容端点，默认 `http://localhost:11434/v1/embeddings`、模型 `nomic-embed-text`）；`api_url` 缺失仍回退 `LocalTfidfBackend`。
- 阈值分档：`conflict_default_threshold()` tfidf 0.7 / embedding 0.55；`conflict_auto_deposit_threshold()` tfidf 0.9 / embedding 0.85。
- `evolve.calibrate()` 门控改为「`is_dense_backend(get_vectorizer())`」—— local-st 直接 `available:true`，且**端点不可达时优雅降级为 `available:false` + reason，绝不 500**（OBS-2 精神延续）。

### B · 自进化自动化
- 新增 `skillforge/auto_loop.py`（`AutoLoopController`）：进程内 `asyncio.Lock` 互斥，保证「手动 `POST /api/evolve/run` / 自动循环 / 开机钩子」同时仅一个 `run_evolve` 在跑。
- 后台周期任务按 `EVOLVE_INTERVAL_MINUTES`（默认 30）循环调用 `run_evolve(trigger="auto_loop")`；`AUTO_EVOLVE_LOOP` 默认 false（不静默写盘）。
- 新增 `GET /api/evolve/auto/status`、`POST /api/evolve/auto/start`、`POST /api/evolve/auto/stop`；`run_evolve` 新增 `trigger` 参数下传至 gold_seed/budget_auto_recall/conflict_rule_deposit，使自动循环条目可识别。
- **B-3 no-op 保护**：gold 已全覆盖且本轮无新增回归/冲突 → 返回 `{ledger_new:[], "no_op":True}`，不写 ledger / metrics，避免空转刷屏。

### C · 前端进化视图增强
- 后端新增 `evolution_metrics` 小表（每次 `run_evolve` 末写 `ts, gold_coverage, f1_acc_before, f1_acc_after`）+ `GET /api/evolve/trends`（按 ts 升序）；`GET /api/evolve/ledger` 增加 `since`/`until`。
- 前端（零构建）：手写 SVG 趋势折线（gold 覆盖度 0~100% + F1 前/后），含空数据占位与 hover tooltip；账本时间线新增「类型下拉 + 时间窗」筛选；保留 🌱播种/▶运行/🔬校准/📤导出，新增 ⚙ 自动进化开/关按钮联动 B-2 端点。

### D · 文档 + 全量回归
- 文档：`docs/prd-evo2-2.md`（增量 PRD）、`docs/arch-evo2-2.md`（增量架构）、`docs/class-diagram-evo2-2.mermaid`、`docs/sequence-diagram-evo2-2.mermaid`、本文交付报告。
- 测试：新增 `tests/`（conftest 用 stdlib `http.server`+`threading` 实现 `MockEmbeddingServer` 确定性稠密向量、合成技能 fixture、`tmp_path` 隔离 `DATA_DIR`）；`test_backend/test_evolve/test_auto_loop/test_trends/test_endpoints` 覆盖全部 P0；`run_regression.sh` + `Makefile(make test)` + `.github/workflows/regression.yml`（P1 CI）。**全部用例固定合成 fixture、mock embedding，不依赖真实 `~/.workbuddy/skills` 与远程 API。**

---

## 4. 验收结果（QA 严过关）

### A 组 全量回归（18 passed / 0 failed）
| 验收项 | 用例 | 结果 |
|--------|------|------|
| A-1 provider 解析 / 回退 / 注册 | test_provider_local_st_returns_embedding_backend / test_provider_openai_without_api_url_falls_back / test_register_vectorizer_custom | PASS |
| A-2 阈值分档 | test_thresholds_embedding_tier / test_thresholds_local_tfidf_tier | PASS |
| A-3 calibrate 门控 | test_calibrate_gating_local_st_available | PASS |
| B-1/B-2 自动循环 | test_auto_loop_start_stop_status / test_run_once_writes_auto_loop_trigger / test_mutex_serializes_concurrent_runs | PASS |
| C-1 metrics + trends | test_metrics_empty_initially / test_metrics_written_and_ascending / test_trends_endpoint | PASS |
| C-2 ledger 过滤 + vectorizer | test_ledger_filter_by_action_type / test_ledger_filter_by_time_window / test_config_vectorizer_returns_provider | PASS |
| B-3 no-op | test_no_op_after_full_coverage | PASS |
| run_evolve 编排 | test_run_evolve_seeds_and_returns / test_conflict_auto_deposit | PASS |

### B 组 独立验证（10/10，QA 单独编写 `verify_independent.py`，新鲜眼光）
- B.1 calibrate 端点不可达 → `available:false` + reason，**无 500** ✅
- B.2 二次 `run_evolve` → `no_op:True` + `ledger_new:[]` + metrics 不新增 ✅
- B.3 trends 空数据 `points:[]` 不报错；填充数据按 ts 升序 ✅
- B.4 自动循环 `false→true→false`（持久单循环 httpx 客户端验证，贴近生产）✅
- B.5 ledger 时间窗过滤正确（未来下界返回空）✅
- B.6 前端零构建：无 package.json/node_modules；`app.js` 4 处手写 SVG；无第三方图表库引用 ✅

---

## 5. 智能路由
- **源码 Bug：无**。源码行为与设计文档完全一致。
- **测试代码 Bug（QA 自修，未改源码）**：首轮 11 failed 根因为 conftest 测试隔离失效（模块顶层 import 绑定 stale 模块），QA 新增 `_rebind_test_modules` 重绑；另修 2 处断言/fixture 错误（openai 无 api_url fixture、calibrate 成功路径无 reason）。修复后 18/18 通过（第 2 轮，符合「最多 2 轮」）。

---

## 6. 已知问题 / 遗留（非阻塞）
1. `auto_loop.start()` 用 `asyncio.ensure_future(_loop())`：在无运行事件循环的独立测试上下文会抛 `DeprecationWarning`（"no current event loop"）+ "Task was destroyed but it is pending"。生产由 async `lifespan` 调用（有运行 loop），无此问题。建议后续改为 `asyncio.get_running_loop().create_task(...)`。
2. Starlette `TestClient` 每次请求新建事件循环，后台 asyncio 任务跨请求被销毁，导致 `status` 在 TestClient 下误报 false；QA 改用持久单循环 `httpx.AsyncClient` 验证（验证方法问题，非源码缺陷）。
3. P1/P2 项（A-4 注册钩子已落地；A-5 阈值持久化、B-3 已落地、C-4 tooltip 已部分、D-3 CI 已落地）其余 P2（A-6 多后端对比、B-5 跨进程锁、C-6 异常标注）留待后续。

---

## 7. 运行 / 部署方式
```bash
cd skill-forge
C:/Users/lenovo/.workbuddy/binaries/python/envs/default/Scripts/python -m uvicorn skillforge.server:app --host 127.0.0.1 --port 8008 --log-level warning
# 浏览器打开 http://localhost:8008 → 进化看板
```
- 启用真实 embedding：本地起 OpenAI 兼容服务（ollama / text-embeddings-inference），在 `data/vectorizer.json` 设 `provider: local-st`（默认指向 `http://localhost:11434/v1/embeddings`）。
- 启用自动循环：启动前设环境变量 `AUTO_EVOLVE_LOOP=true`（默认 false）。
- 全量回归：`make test` 或 `pytest tests/ -q`（需 pytest + httpx，仅测试期）。

## 8. 文件清单（v2.2 改动）
后端修改：`skillforge/__init__.py`、`config.py`、`scorer.py`、`simulator.py`、`evolve.py`、`simbank.py`、`server.py`
后端新增：`skillforge/auto_loop.py`
前端修改：`frontend/index.html`、`frontend/app.js`、`frontend/style.css`
测试/脚本新增：`tests/conftest.py`、`tests/test_backend.py`、`tests/test_evolve.py`、`tests/test_auto_loop.py`、`tests/test_trends.py`、`tests/test_endpoints.py`、`run_regression.sh`、`Makefile`、`.github/workflows/regression.yml`、`verify_independent.py`
文档新增：`docs/prd-evo2-2.md`、`docs/arch-evo2-2.md`、`docs/class-diagram-evo2-2.mermaid`、`docs/sequence-diagram-evo2-2.mermaid`、`docs/delivery-evo2-2.md`
