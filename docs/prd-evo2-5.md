# PRD · SkillForge v2.5.0-evo（增量）

> 版本线：2.4.0-evo → 2.5.0-evo（由主理人 齐活林 处理 `__init__` 版本号与提交/重启，本增量仅出分析与文档，不改源码）。
> 约束：零新增 pip 运行时依赖（仅 stdlib + fastapi/uvicorn/pyyaml/tiktoken）；前端零构建（原生 HTML/CSS/JS + 手写 SVG）；保留既有接口签名（破坏性变更须标注给架构师做增量文档）。
> 本 PRD 基于**逐文件深读 + 两点实证复现**产出，不重复 v2.4 已交付的 9 项能力。

---

## 1. 产品目标

在 v2.4「加引导 + 补盲区 + 可观测 + 收口」之上，对 v2.5 做**查缺补漏与加固**：

- **G1（正确性收敛）**：消除自进化闭环里会污染持久化数据（custom_rules / ledger）的真实缺陷。
- **G2（健壮性加固）**：补齐并发写盘、临时文件、外部变化误报三类脆弱路径。
- **G3（可观测/UX 闭环）**：让已采集但不可见的数据可见，并修掉"假死"的 UI 控件与定位失效。

正交、不堆砌：P0 只放会**真实损坏数据/安全**的项；P1 放有体感的正确性与并发问题；P2 放锦上添花。

---

## 2. 用户故事

- US-1（作为自进化系统）：我希望重复运行进化引擎**不会**反复往 custom_rules.json 与账本里塞入重复的冲突规则，避免规则文件无限膨胀、校验噪音累积。
- US-2（作为技能作者）：我希望只有**内容真正变化**时才被识别为"外部变化"并写账本，git checkout / 编辑器自动保存导致的 mtime 变动不应触发误报。
- US-3（作为运维）：我希望高频写库（进化 + 调用追踪）在并发下不抛 "database is locked" 500。
- US-4（作为前端用户）：我希望冲突检测视图里选"embedding"后端**真的生效**，仿真趋势数据**真的显示在看板**，异常点"定位账本"**真的能高亮到对应行**。
- US-5（作为安全评审）：我希望 API 写盘路径不使用已废弃、有竞态风险的 `tempfile.mktemp`。

---

## 3. 需求池

### 3.1 P0 — 必须修复（会真实损坏数据/安全）

#### P0-1 冲突规则沉淀去重（修 `run_evolve` ③ + `custom_rules.deposit_custom_rule`）

- **现象（已实证）**：用两个 description 完全相同的技能跑两轮 `run_evolve`，`custom_rules.json` 出现 **2 条**冲突规则、账本 `conflict_rule_deposit` **2 条**。根因：`run_evolve` 第 ③ 步对 `detect_conflicts` 返回的每对 ≥ 阈值技能直接 `deposit_custom_rule`，**没有任何去重**；`deposit_custom_rule` 又永远是 append 新 `CONFLICT-NN`。技能描述不变 → 相似度不变 → 每轮都再沉淀。开启 `AUTO_EVOLVE_LOOP` 后会按 `EVOLVE_INTERVAL_MINUTES` **永久无限累积**。
- **依据**：`skillforge/evolve.py` 第 226–249 行；`skillforge/custom_rules.py` 第 38–62 行。复现脚本：2 轮 run_evolve → 规则数=2、账本=2。
- **验收**：
  1. 相同 keyword_cluster 的冲突规则在同一文件中**唯一**（idempotent）。
  2. 连跑 N 轮后 `custom_rules.json` 中"该对技能"仍只有 1 条；账本 `conflict_rule_deposit` 对该对仅 1 条。
  3. 真出现**新的**高相似对时仍能正常新增 1 条。
- **接口兼容性**：`deposit_custom_rule(..., dedupe: bool = True)` 新增可选参数（向后兼容）；去重键为 `tuple(sorted(keyword_cluster))`。也可在 `run_evolve` 沉淀前用 `load_custom_rules()` 做前置过滤。**须标注给架构师**：若选"仅在 run_evolve 内过滤"，需确认手动「沉淀为新规则」按钮（app.js `depositRule`）同样获得去重保护。
- **测试建议**：新增 `test_conflict_deposit_no_duplicate`（连跑两轮断言规则数=1）补 `tests/test_evolve.py`。

#### P0-2 写盘临时文件改用安全 API（修 `server.py` `/api/clean`、`/api/apply`）

- **现象**：`clean()` 与 `apply()` 用 `tempfile.mktemp(suffix=".md")` 创建临时解析文件，再 `write_text` → `parse_skill_file` → `unlink`。`tempfile.mktemp` 官方明确标注**不安全**（CWE-377：攻击者可在返回路径与前序 `write_text` 之间预建/劫持该文件）。
- **依据**：`skillforge/server.py` 第 174–179 行（`clean`）、第 191–198 行（apply 内另有 `path.with_suffix(".md.bak")` 备份）。
- **验收**：改用 `tempfile.NamedTemporaryFile(..., delete=False)` 或 `mkstemp`，用完 `finally` 中确保删除；不出现 `mktemp`。
- **接口兼容性**：纯内部实现替换，无签名变化。

### 3.2 P1 — 重要（有体感的正确性 / 并发 / 假死控件）

#### P1-1 签名检测剔除 mtime 误报（修 `skill_signature.py`）

- **现象（已实证）**：基线建立后，仅 `os.utime` 改 mtime（**内容不变**），`detect_external_change()` 返回 `external_change=True`，并导致 `run_evolve` 写 1 条 `skill_signature_change` 账本。根因：复合指纹把 **MTIME** 纳入哈希（MANIFEST+CONTENT+MTIME），任何触碰文件的工具（git、编辑器自动保存、备份、rsync）都会制造"假外部变化"，进而每轮重复 `bootstrap_gold` + 写账本。
- **依据**：`skillforge/skill_signature.py` 第 93–104 行（MTIME 段参与 `sha256`）。复现：mtime-only touch → external_change=True、账本=1。
- **验收**：仅当"清单变化（增/删文件）或关键文件内容哈希变化"时 `external_change=True`；纯 mtime 变更不再触发。MTIME 可保留为展示字段但**不参与哈希**。
- **接口兼容性**：`compute_signatures` / `load_saved_signatures` 返回结构不变（仍 `{name: hex}`）；`SIGNATURE_SCHEMA=2` 保持不变（无需迁移）。

#### P1-2 SQLite 并发写安全（修 `simbank.py` / `tracker.py` `_conn()`）

- **现象**：`_conn()` 每次调用都 `connect` + `executescript(_SCHEMA)`，默认 rollback journal、`busy_timeout=0`。`run_evolve` 被文件锁包裹（仅同进程内），但 `/api/track`、`/api/apply`、`/api/stats` 等会**同时**开独立连接写同一 SQLite；长事务下并发写易抛 `database is locked` → 500。多实例部署（跨进程文件锁生效）时该风险更突出。
- **依据**：`skillforge/simbank.py` 第 83–88 行；`skillforge/tracker.py` 第 24–29 行。
- **验收**：在 `_conn()` 中启用 `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;`（WAL 允许读写并发、busy_timeout 避免瞬时锁即 500）；现有读写逻辑、表结构不变。
- **接口兼容性**：无函数签名变化。

#### P1-3 冲突检测视图"embedding"后端选项失效（修前端 + 后端）

- **现象**：冲突检测视图有 `local-tfidf / embedding-API` 两个 radio，但 `loadConflicts()` 只发 `/api/conflicts?threshold=`（**不带 backend**），而后端 `get_conflicts(threshold=None)` 也**不支持 backend 参数** → 选 embedding 永远无效，实际始终用 `vectorizer.json` 配置的后端。对比「调度模拟」视图的 backend radio 是生效的（后端 `/api/sim/schedule` 接收 `backend_name`），两处行为不一致、且给用户"选了没反应"的误导。
- **依据**：`frontend/app.js` 第 492–516 行；`skillforge/server.py` 第 308–314 行。
- **验收**：要么（a）给 `/api/conflicts` 增加 `backend` 查询参数并透传 `conflict_default_threshold(backend)`/`detect_conflicts(backend_name=)`，前端把所选 radio 带上；要么（b）若刻意统一走 vectorizer 配置，则**移除该 radio** 并加一句说明，避免假死控件。
- **接口兼容性**：若选 (a) 为 `get_conflicts` 增加可选 `backend` 参数（向后兼容，缺省沿用现有行为）。

#### P1-4 仿真趋势数据"已采集但不可见"（前端 dashboard）

- **现象**：`run_schedule_sim` / `run_cost_sim` 都会写 `scheduling_sim` / `cost_sim`，但 `renderDashboard()` 虽然 `GET /api/sim/trends` 却**从不渲染**这两类趋势（仅渲染 tracker 的按天节省与排行）。已落库的趋势数据对用户完全不可见，属"死的可观测性"。
- **依据**：`frontend/app.js` 第 227–228 行（注释明示"保留读取以备扩展"但未实现）；后端 `simbank.get_schedule_trend` / `get_cost_trend` 已就绪。
- **验收**：看板新增「调度模拟覆盖度 / 成本节省」卡片，或至少在仿真沙盘对应结果区展示"历史趋势"。至少二选一落地，让已采集数据可见。
- **接口兼容性**：无后端签名变化；纯前端取数渲染。

### 3.3 P2 — 锦上添花

#### P2-1 异常点"定位账本"按 ts 匹配失效

- **现象**：B-4 浮层「定位账本条目」用异常点的 `ts`（来自 `evolution_metrics`）去匹配 ledger 行的 `ts`。但两者由 `run_evolve` 内**各自独立调用 `_now()`** 生成（微秒级不同），永不相等 → 高亮静默失败。
- **依据**：`skillforge/evolve.py` 第 296–300 行（metric）与 ledger 写入（各 `log_evolution`）；`frontend/app.js` 第 1065–1078 行。
- **验收**：让一轮 `run_evolve` 复用同一个 `run_start` 作为所有 ledger 条目与 metric 的 `ts`（或把 metric 的 run_start 回填到对应的 ledger 语义），使定位可命中。

#### P2-2 `run_evolve` 内重复全量扫描

- **现象**：单次 `run_evolve` 内 `scan_skills()` / `compute_signatures()` 被调用约 4–6 次（bootstrap×1~3、schedule、conflicts、coverage、低水位），每次都重新 `yaml.safe_load` + tiktoken 全量解析所有 SKILL.md。技能集大时有明显冗余。
- **验收**：在 `run_evolve` 入口一次性 `scan_skills()` 并向下传递，避免重复 IO/解析。可选优化。

#### P2-3 `bootstrap_gold(force=True)` 实为 no-op

- **现象**：前端「🌱 播种 Gold 样本」用 `confirm` 提示"强制重新播种缺失技能"，但 `force=True` 并未覆盖"全部已覆盖→提前返回"的门槛（与 `force=False` 行为一致）；该按钮的"强制"语义是误导。
- **验收**：要么真正尊重 `force`（忽略覆盖门槛、重建缺失项，仍不删既有样本），要么把文案改为"仅补充缺失样本"以消除误导。

#### P2-4 锁占用时前端"进化完成"反馈误导

- **现象**：手动「▶ 运行自主进化」若被进程内 asyncio 锁占用而跳过，后端返回 `{skipped:True,...}`，前端仍 toast「进化完成：播种 0 · 自动回调 0 · 沉淀规则 0」，不告知用户"本轮被跳过"。
- **验收**：前端据 `skipped` 字段显示「本轮被跳过（其他入口正在运行）」。

#### P2-5 `USER_SKILLS_DIR` 与 `SKILLS_DIRS` 分裂风险

- **现象**：前端列技能取自 `SKILLS_DIRS`，而 evolve/覆盖度/播种取自 `USER_SKILLS_DIR`。若用户用 `SKILLS_DIRS` 指向与 `USER_SKILLS_DIR` 不同的集合，会出现"前端列出很多技能、但 Gold 覆盖度=0 / 永不播种"的割裂。默认配置下 `USER_SKILLS_DIR ⊆ SKILLS_DIRS`，故仅自定义 env 时触发。
- **验收**：在文档/配置注释中明确二者关系；或在 `config` 启动时若 `SKILLS_DIRS` 含 `USER_SKILLS_DIR` 之外目录，给出日志提示。

---

## 4. UI 线框（仅变更部分）

### P1-3 冲突检测视图（方案 a：让后端选择生效）

```
[ 向量后端 ] (•) local-tfidf（零依赖）   ( ) embedding-API
[ 相似度阈值 ] ──────────●──── 0.70
[ 🔄 重新计算 ]
```
- 选 embedding-API 时，请求变为 `/api/conflicts?threshold=0.70&backend=embedding`，后端按所选后端探测/打分。
- 若选方案 b（移除 radio），则改为一行说明文字："冲突检测统一使用当前后端（见进化视图「当前后端」），无需此处切换。"

### P1-4 看板新增仿真趋势卡片

```
┌─ 调度模拟覆盖度趋势 ────────────┐   ┌─ 成本节省趋势 ────────────────┐
│ [ 折线 SVG：accuracy_after 时序 ] │   │ [ 柱状 SVG：每次 cost_sim 节省 ] │
└─────────────────────────────────┘   └────────────────────────────────┘
```
- 数据取自 `GET /api/sim/trends`（scheduling_sim / cost_sim），复用 `_drawTrend` 手写 SVG 风格。

### P2-4 进化跳过反馈

```
toast: 「本轮被跳过：其他入口（自动循环/开机）正在运行进化」
```
- 依据响应 `skipped===true` 显示，不再显示"进化完成 0/0/0"。

---

## 5. 强化巩固（已验证 v2.4 稳健，本次不作改动，仅登记）

逐项核对 v2.4 交付的 9 项，确认代码层面已落实且基本稳健：

1. **使用说明模态（P0）** ✅ 代码完整：`initOnboarding` 用 `localStorage` 键 `skillforge_onboarding_v2_4`、顶栏「❓ 使用说明」可唤起、遮罩/X/「开始使用」/Esc 多入口关闭，首进自动弹。
2. **A-4 `/api/evolve/pressure`** ✅ `server.get_evolve_pressure` 读 `skill_signature_change` 最新账本并解析 `after_val` 的 added/removed/changed；前端 `loadPressure()` 已接入进化视图。*（小瑕疵见 P2-1）*。
3. **A-5 heartbeat 节流** ✅ `run_evolve` 中"相同值 + 间隔 < `HEARTBEAT_MIN_INTERVAL_SEC` → 跳过写 metrics"，且首行/值变/超间隔必写，逻辑正确。
4. **B-4 异常点击下钻** ✅ `bindAnomalyClick` 事件委托、`#anomalyDetail` 浮层、异常点 `data-*` 注入均到位；仅"定位账本"因 ts 不匹配失效（见 P2-1）。
5. **C-4 锁超时降级** ✅ `FileLock` 超时 `acquired=False` + `logger.warning` + 安全 skip；`test_filelock.py` 覆盖占用/超时/禁用。
6. **D-3 多候选探测** ✅ `probe_candidates(config.EMBEDDING_CANDIDATE_URLS)` 短路返回首个可用；lifespan 与显式刷新均走此路径。
7. **R-1 复合指纹 `SIGNATURE_SCHEMA=2`** ✅ `load_saved_signatures` 对 schema 不符返回 `{}`（静默重建）；`test_signature.py` 覆盖基线/新增/删除/改 scripts/迁移。*（误报面见 P1-1 mtime）*。
8. **R-2 vectorizer None 路径先探测** ✅ `ensure_default_vectorizer` 在 `_ollama_available is None` 且未传候选时先 `probe_candidates` 再分支，不再静默回退。
9. **R-3 `pytest.ini` markers** ✅ `pytest.ini` 注册 a/b/c/d 四组；全部测试以 `pytestmark = pytest.mark.<x>` 使用，`PytestUnknownMarkWarning` 已消除。

结论：v2.4 的 9 项功能**主体稳健可用**，本轮不回退、只在其上补漏（P1-1、P2-1 是对 R-1 / B-4 的边角修正）。

---

## 6. 待确认问题（§待确认问题）

1. **P0-1 去重落点**：去重放在 `custom_rules.deposit_custom_rule`（更彻底，连手动沉淀也受保护）还是只在 `run_evolve` 内前置过滤（改动更小）？手动「沉淀为新规则」按钮是否应允许"明知重复仍强制新增"？
2. **P1-3 后端切换**：冲突检测是否要支持运行时切换 embedding（方案 a，需后端加 `backend` 参数），还是直接移除该 radio（方案 b，统一走 vectorizer 配置）？哪个更符合产品意图？
3. **P1-4 展示范围**：仿真趋势是放在"看板"独立卡片，还是回写在"仿真沙盘"结果区？是否要限制历史点数防 SVG 过宽？
4. **P1-1 兼容性**：剔除 mtime 后，是否仍有用户依赖"仅 mtime 变化算外部变化"的语义？建议改为"内容/清单变化才算"，请确认可接受。
5. **WAL 副作用**：启用 SQLite WAL 会在 `data/` 下产生 `-wal`/`-sh` 文件，是否影响现有的备份/拷贝流程？是否需在主理人重启脚本里处理。
6. **范围裁剪**：本轮只做分析+文档，源码改动由后续迭代按本 PRD 落地；P0 是否定为"发布前必须全修"，P1 是否进 v2.5 同一发版，P2 是否顺延 v2.6？
