# PRD · SkillForge 通用 Prompt 简化器（增量 evo2-9 · 本地语义压缩）

> 版本线：2.8.0-evo → 2.9.0-evo（版本号由主理人处理 `__init__`，本增量仅出分析与文档，不改源码）。
> 约束：零新增 pip 运行时依赖（仅 fastapi/uvicorn/pyyaml/tiktoken）；前端零构建（原生 HTML/CSS/JS）；接口向后兼容。
> 范围**仅**限「通用 Prompt 简化器」：`prompt_simplifier.py` / `/api/simplify` / 前端「简化」视图。**不**动 `cleaner.py` / SKILL.md 清洗。
> 本增量**叠加于 v2.8 之上**：v2.8 的 13 类规则、`PRESETS`（5 基础类）、保护机制、`explicit = (rules is not None)` 契约一律沿用，不推翻。
> 硬契约（不可破坏）：`rules is None` 时后端走 `PRESETS`，其 `simplified_text` 必须**逐字等于 v2.5**（仅那 5 个基础类）。**任何 v2.9 新增行为不得改变该路径输出。**
> 复用资产：`skillforge/scorer.py` 的 local-st `EmbeddingBackend`（`get_vectorizer()` / `vectorize()` / `similarity()`，v2.2 落地、开箱可用、零新增依赖）——注意主理人简述中的 `backend.py` 实为 `scorer.py` 内的该 provider。

---

## ① 产品目标

- **G1（补比率短板·仍本地）**：在 v2.8 规则式（10–40% 视冗余）之上，新增**本地、确定性、可复现**的语义级压缩——近义/重复句折叠，让"省 token"能力更接近 LLMLingua 类语义压缩器的叙事，同时**守住隐私/离线/免费/零依赖**定位（复用 local-st，绝不引入云 API）。
- **G2（显式可控·零回归）**：`semantic_compress` 为 **explicit-only** 规则（`default_in_presets: False`），仅用户显式勾选时生效；`rules=None` 契约不受影响；embedding 不可用时**优雅回退纯词法、不崩不报错**。
- **G3（不做抽象重写）**：明确**排除 abstractive summarization**（需 LLM 生成，违背"确定性/可复现/免费/隐私优先"，且本地无内置生成模型）。v2.9 只做**抽取式**语义压缩（近义句折叠 + 可选低信息句剪枝）。

---

## ② 用户故事

- US-1（作为提示词作者）：我希望简化器不仅能删"请/但是/啊"这类词法冗余，还能识别"请帮我检查一下这段代码"与"帮我看看这段程序有没有问题"这种**意思重复的两句话**，只留第一句，进一步压缩长 prompt。
- US-2（作为隐私/离线用户）：我希望这个语义压缩**全程本地**（复用项目已有的 local-st embedding），不上传我的 prompt 到任何云端；若我本机没配 embedding，它就该**安静跳过**而不是报错崩溃。
- US-3（作为进阶用户）：我希望用一个**阈值滑块**（0.80–0.98）控制"多像才算重复"，并自行决定是否开启"重要性剪枝"二级能力；老接口（`{text}` 或 `{text, mode}`）行为不变。

---

## ③ 需求池

### P0 — 必须（新能力 / 契约相关）

| 编号 | 需求 | 验收标准 |
|---|---|---|
| P0-1 | 新增 `semantic_compress` 规则类（explicit-only，后端） | ① 新增 `_rule_semantic_compress(work, aggressive_like, explicit, threshold, prune)` 并注册进 `RULE_REGISTRY`/`ALL_RULE_IDS`/`CANONICAL_ORDER`（`ALL_RULE_IDS` 13→**14**）；`default_in_presets: False`；② 不进入 `PRESETS`，`rules=None` 输出零变化；③ 与 `duplicate_clauses`/`punctuation_compress` 同族（explicit-only）。 |
| P0-2 | 能力1·近义/重复句检测（抽取式） | ① 按句切分（保护占位符 `\x00P/K\x00` 视为原子单元，不在其内部断句）；② 逐句调用 local-st `vectorize()` 得句向量；③ 两两余弦相似度 ≥ `threshold`（默认 ≈0.9）判为语义重复，保留**首次出现**、折叠后续；④ 主干/指令/条件/代码/URL 不被误删（复用 v2.6 保护）。 |
| P0-3 | embedding 复用 + 优雅回退 | ① 复用 `scorer.get_vectorizer()` 的 local-st `EmbeddingBackend`（`vectorize`/`similarity`），**零新增依赖**；② 进程内句向量缓存（按句文本 key）降延迟，避免同句重复 embedding；③ 当 `get_vectorizer()` 非稠密后端（local-tfidf）或端点不可达时，**静默跳过** `semantic_compress`（返回 work 不变、count=0、变更日志注明"语义压缩已跳过（embedding 不可用）"），绝不 500 / 不抛未捕获异常。 |
| P0-4 | 接口与前端默认生效 | ① `/api/simplify` 新增可选 `semantic_threshold`（float，默认 0.9）与 `semantic_prune`（bool，默认 False），缺省时取默认；非法/越界值静默回落默认，不 500；② 前端 `SIMPLIFY_RULE_IDS` 13→14；进阶精简组新增 `semantic_compress` 复选框 + 阈值滑块（0.80–0.98，默认 0.90）；③ `semantic_compress` **默认不勾选**（仅 explicit，见 §⑤ Q1），请求体 `rules` 含该 id 时附带阈值/剪枝参数。 |

### P1 — 重要（能力2 / 体验）

| 编号 | 需求 | 验收标准 |
|---|---|---|
| P1-1 | 能力2·抽取式重要性剪枝（二级，可选） | ① 以全部句向量质心为「主题向量」，计算每句与质心余弦；② 低于 `prune` 阈值（默认复用或低于 `threshold`）的低信息句（纯客套/过渡展开，且无指令动词/条件/参数/代码）标记或折叠；③ **仅当 `semantic_prune=True` 时启用**，默认关；④ 不删含指令性内容/否定/代码/URL 的句子。 |
| P1-2 | localStorage 版本升 `v2_9` | `saveSimplifyState`/`loadSimplifyState` 读写 `skillforge_simplify_v2_9`，缺失回退 `v2_8` 迁移；默认进入应用「保守」预设（**不含** `semantic_compress`，与 Q1 一致）。 |
| P1-3 | 变更日志标注 | `changes` 条目细化：`"折叠 N 处语义重复句 [semantic_compress]"`、`"剪枝 M 句低信息内容 [semantic_compress]"`、`"语义压缩跳过（embedding 不可用）[semantic_compress]"`。 |

### P2 — 锦上添花

| 编号 | 需求 | 验收标准 |
|---|---|---|
| P2-1 | 阈值/剪枝参数持久化 | 阈值滑块与剪枝开关随 `rules` 一起记忆（localStorage），下次恢复；可选"保存为我的预设"。 |
| P2-2 | 多语言句向量适配 | 中文/英文 prompt 均可用 local-st 句向量；验证英文近义句（"Please check the code" / "Could you review this program"）折叠。 |
| P2-3 | 与现有规则组合验证 | `semantic_compress` 与 `logical_connector`/`filler_particles`/`duplicate_clauses` 同开时，顺序正确、无双重计费、输出确定性可复现。 |

---

## ④ UI 设计稿（新「简化」页 · 进阶精简组变更部分）

仅描述 v2.8 之后的**增量**；`进阶精简` 分组在 v2.8 已有的 6 个 checkbox 基础上，新增 `semantic_compress` 复选框 + 阈值滑块：

```
┌─ 简化规则（可多选）──────────────────────────────────────────┐
│ 基础裁剪（默认启用）                                          │
│  [☑] 礼貌填充词   [☑] 冗长角色描述   [☑] 空列表项             │
│  [☑] 重复指令     [☑] 空行折叠                                │
│ 进阶精简（可选）                                              │
│  [☑] 元评论/过渡句  [☐] 弱语气词  [☐] 冗余副词                │
│  [☐] 过长示例压缩  [☐] 跨句完全重复  [☐] 连续标点折叠        │
│  [☐] 语义压缩 semantic_compress            ← 新增（默认关）   │
│       相似度阈值  [─────────●──────] 0.90   (0.80 – 0.98)    │
│       □ 启用重要性剪枝（二级）                                │
│       （仅显式勾选生效；需本地 embedding，不可用时自动跳过）   │
│ 预设：[ 保守 ]  [ 激进 ]   （当前：保守 / 自定义）            │
└──────────────────────────────────────────────────────────────┘
        ↓ 结果区（沿用现 card：结果 textarea + 4 项统计 + 复制/导出 + 变更日志）
```

- 阈值滑块：范围 **0.80–0.98**，步长 0.01，默认 **0.90**；值随 `rules` 下发（映射 `semantic_threshold`）。
- 「启用重要性剪枝」勾选框：默认**不勾**（映射 `semantic_prune=False`）。
- `semantic_compress` 复选框默认**不勾**（仅 explicit，见 §⑤ Q1）；勾选后才允许滑块/剪枝生效。
- 请求：`POST /api/simplify` 体 `{text, rules:[...], semantic_threshold:0.90, semantic_prune:false}`；不勾选时 `rules` 不含该 id，后端跳过（向后兼容，纯老调用方不受影响）。

---

## ⑤ 待确认问题

1. **Q1 · `semantic_compress` 是否进默认「均衡/保守」预设？**（主理人倾向：**仅 explicit、不进 PRESETS**）
   建议：前端「保守」预设**不**默认包含 `semantic_compress`（默认不勾选），用户需主动开启。理由：① 它需要本地 embedding，默认开启可能在无 embedding 环境静默无效、造成"开了没反应"困惑；② 与 `duplicate_clauses`/`punctuation_compress` 的"explicit-only 不进 PRESETS"族保持一致；③ 语义压缩属"激进/可选"语义，不宜塞进默认均衡体验。若最终决定进默认预设，则须同步改 `SIMPLIFY_PRESETS.balanced` 且仍保证 `rules=None` 契约不动（前端预设 ≠ 后端 PRESETS）。

2. **Q2 · 阈值默认值与可调区间**
   建议默认 **0.90**、区间 **0.80–0.98**。0.90 偏保守（仅高度相似才折叠，防误删）；下限 0.80 留给"更激进去重"用户，上限 0.98 接近"几乎字面相同才删"。是否接受此区间，或需更宽（如 0.70）？

3. **Q3 · 是否默认开启能力2（重要性剪枝）？**
   建议默认**关闭**（`semantic_prune=False`）。理由：剪枝依赖"与质心相似度"判断低信息句，误删风险高于近义句折叠，且属二级增强；先以近义句折叠（能力1）为主打，剪枝作为显式开关更安全。是否同意默认关、或默认开？

---

## ⑥ 落地改动清单（供架构师速览）

- `prompt_simplifier.py`：新增 `_SEMANTIC_THRESHOLD_DEFAULT=0.90`、`_SEMANTIC_THRESHOLD_MIN=0.80`、`_SEMANTIC_THRESHOLD_MAX=0.98`；`_rule_semantic_compress(work, aggressive_like, explicit, threshold, prune)`；`ALL_RULE_IDS` +1（→14）、`CANONICAL_ORDER` 末位追加 `semantic_compress`、`RULE_REGISTRY` +1（`default_in_presets: False`）；`simplify_prompt` 主循环在 `punctuation_compress` 之后插入 `semantic_compress` 分支（均 `_tag(..., explicit)`），并接收 `semantic_threshold`/`semantic_prune` 参数（缺省取默认、越界回落）。
- `server.py`：`/api/simplify` 读取可选 `semantic_threshold`/`semantic_prune`，透传 `simplify_prompt`（非 list 字段不影响 `rules=None` 契约）。
- `scorer.py`（复用，不改或极小增强）：`get_vectorizer()` 返回 local-st `EmbeddingBackend`；`vectorize()`/`similarity()` 已具备；新增进程内句向量缓存（可选，P0-3）。
- `frontend/app.js`：`SIMPLIFY_RULE_IDS` 13→14；进阶精简组新增 `semantic_compress` 复选框 + 阈值滑块 + 剪枝勾选；`SIMPLIFY_PRESETS` 依 Q1 决策（默认不进）；`localStorage` key 升 `v2_9` 并迁移 `v2_8`；`doSimplify` 下发 `semantic_threshold`/`semantic_prune`。
- `frontend/index.html`：`进阶精简` 分组新增 `data-rule="semantic_compress"` 复选框 + 阈值 `<input type="range">` + 剪枝 `<input type="checkbox">`。
- 测试（QA 后续写）：`test_semantic_compress_near_dup_fold` / `test_semantic_compress_threshold_boundary` / `test_semantic_compress_embedding_fallback` / `test_semantic_compress_rules_none_zero_regression` / `test_semantic_compress_combines_with_existing`；`test_all_rule_ids_exact` 由 13 改为 14。
