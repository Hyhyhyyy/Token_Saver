# PRD · SkillForge 通用 Prompt 简化器（增量 evo2-8 · token 用量维度优化）

> 版本线：2.7.0-evo → 2.8.0-evo（版本号由主理人处理 `__init__`，本增量仅出文档，不改源码）。
> 约束：零新增 pip 运行时依赖；前端零构建（原生 HTML/CSS/JS）；`/api/simplify` 向后兼容。
> 范围**仅**限「通用 Prompt 简化器」：`prompt_simplifier.py` / `/api/simplify` / 前端「简化」视图。**不**动 `cleaner.py` / SKILL.md 清洗。
> 本增量**叠加于 v2.7 之上**：v2.7 的 11 类规则、PRESETS、保护机制一律沿用，不推翻。
> 硬契约（不可破坏）：`rules is None` 时后端走 `PRESETS`，其 `simplified_text` 必须**逐字等于 v2.5**（仅那 5 个基础类）。**任何 v2.8 新增/增强行为不得改变该路径输出。**
> 时机：v2.8 实现必须在 **v2.7 提交后**进行（同文件冲突），PRD 先行。

---

## 1. 产品目标

- **G1（削减 token 浪费）**：在 v2.7「思维痕迹」过滤之上，针对用户点名的 **token 用量三维度**中的两块可低成本削减项——**信息重复**与**标点冗余**——做精准压缩，降低每轮无效 token 开销，且不伤可读性。
- **G2（绝不伤指令 · 零回归）**：所有新增/增强必须严守「保留关键信息原则」（§6）与 `rules=None ≡ v2.5` 硬契约（§0）；新增行为**仅当用户显式勾选（下发 `rules`）时生效**，预设/老 API 路径零变化。

---

## 2. 用户故事

- US-1（作为提示词作者）：我希望简化器把"请提取所有超时请求。请提取所有超时请求。"这类跨句完全重复，以及"总结一下，简单来说就是总结"这类字面重复堆叠也去掉，但"删除 config.py 中的 retry 配置。删除 output.log 中的错误行。"里只共享动词"删除"的两句**绝不**被误并；`!!!`/`。。。`/`???` 折叠成单标点，但 `!!`、`……`、`——` 原样保留。
- US-2（作为 API 调用方 / 老接口用户）：我不传 `rules`（或 `{text, mode}`）时，v2.8 的输出必须**与 v2.5 逐字一致**；新压缩只是我主动勾选/显式传 `rules` 时的增量，绝不背着我改老行为。

---

## 3. 非目标（明确不做）

- **不通顺化规则**：**不做**将口语/不通顺改写为通顺的规则。理由（主理人裁定）：①不通顺/口语组合 BPE 切更碎→更费 token，但②"通顺化"本身会**增** token 且**易误改指令语义**，收益为负。v2.8 不新增任何 fluency-normalization 规则。
- **近义 / 同义归并**：**不做**"总结/概述/归纳"这类**同义词**视为同一要点去重。v2.8 仅做**字面完全重复**（identical substring / 整句）。同义归并留待后续版本（非本期需求，见 §7 Q2）。
- **常规单标点不删、语义标点不删**：单 `。！？` 不处理（省极少且损可读性）；省略号 `…`/`……`、破折号 `——`、ASCII `...` 等语义标点**永不折叠**。

---

## 4. 需求池

### P0 — 必须（重复去重增强 · 契约相关）

| 编号 | 需求 | 验收标准摘要 |
|---|---|---|
| P0-1 | 新增 `duplicate_clauses`（explicit-only）承载跨行/跨句**完全重复子句**去重（字面 identical）；`duplicate_lines` 保持 v2.5 整行去重 base 不变 | ① `duplicate_lines` 整行去重（v2.5 base）恒生效不变；② 新增 explicit-only 规则 `duplicate_clauses` 做跨行/跨句字面重复子句去重；③ 两新 id 均不进 `PRESETS`，`rules=None` 输出零变化；④ 见 §5 验收样例 |

### P1 — 重要（轻量标点压缩 · 低优先级）

| 编号 | 需求 | 验收标准摘要 |
|---|---|---|
| P1-1 | 新增 `punctuation_compress` 规则类（连续重复标点折叠） | ① 折叠 3+ 连续 `。！？.!?` → 单；② 排除 `…/——/...` 语义标点；③ 不进 `PRESETS`，`rules=None` 零变化；④ 见 §5 验收样例 |

### P2 — 无（本期无 P2 需求）

> 近义/同义归并、通顺化、英文 filler 变体等均为**未来方向**，不列为 v2.8 需求。

---

## 5. 各需求验收标准（具体输入输出样例）

### P0-1 · 跨行/跨句完全重复子句去重（仅 explicit 路径生效）

| 用例 | 输入 | 期望输出 | 说明 |
|---|---|---|---|
| 整行重复（v2.5 已覆盖，回归保留） | `请提取超时请求。\n请提取超时请求。` | `请提取超时请求。` | base 整行去重，恒生效 |
| 跨句完全重复子句（**新增**） | `请确保输出 JSON。请确保输出 JSON 并校验字段。` | `请确保输出 JSON。并校验字段。` | 重复子句"请确保输出 JSON"（≥10字）删第二副本 |
| 字面重复词（跨句） | `总结一下，简单来说就是总结。` | `总结一下，简单来说就是。` | 字面"总结"重复删冗余副本（同义"概述/归纳"不在本期） |
| 保护·共享动词非完全重复 | `删除 config.py 中的 retry 配置。删除 output.log 中的错误行。` | **不变** | 仅共享动词"删除"，非完全重复子句，不误并 |
| 保护·代码/URL 内重复 | fenced/行内代码块内重复行 | **原样保留** | 受保护 token 永不处理 |
| 保护·阈值下限 | `非常非常重要。非常非常重要。` 等叠词/短重复 | **默认不处理** | 短于阈值的非句末重复（建议 ≥4 汉字 或 整句收尾于 `。！？`）不删，避免误伤强调 |

> **阈值判定（待架构师拍板，见 §7 边界点）**：跨句去重单元须满足 (a) 长度 ≥ 阈值（建议 ≥4 个汉字）**或**(b) 为以 `。！？` 收尾的**整句**完全重复；二者皆不满足则不处理。"用不同表述强调同一要点"属近义，因本版仅做 exact match 天然不触，无需额外规则。

### P1-1 · 连续重复标点折叠（仅 explicit 路径；不进 PRESETS）

| 用例 | 输入 | 期望输出 | 说明 |
|---|---|---|---|
| 三连问号 | `真的吗？？？` | `真的吗？` | 折叠 |
| 三连叹号 | `好的！！！` | `好的！` | 折叠 |
| 双叹号（Q3 边界） | `好的！！` | **不变** | 仅 2 个不折叠，保护强调语境 |
| 省略号保留 | `他说……` | **不变** | 语义标点不折叠 |
| 破折号保留 | `这是重点——记牢` | **不变** | 语义标点不折叠 |
| 常规单标点 | `你好。请开始。` | **不变** | 单标点不处理 |
| 代码内标点 | 受保护 token 内 `???` | **原样保留** | 不污染代码 |

---

## 6. 保留关键信息原则（硬约束 · 不变量）

新增/增强**必须**满足以下不变量；任一条违反即判回归失败：

1. **指令性动词不删**：删除/提取/过滤/生成/检查/创建/返回/禁止/确保… 不因子句去重被移除（整词匹配 + explicit 门控保障）。
2. **完全重复判定精确**：仅删 **identical（逐字相同）** 子句/整句副本；不靠相似度，不触碰同义改写句。
3. **参数与关键名词保护**：变量名/API 名/路径/数字/专名靠整词匹配不误伤；代码块/行内代码/URL 复用 `_PROTECT`/`_restore` 冻结，新增逻辑作用其外。
4. **否定词与条件保护**：去重/折叠不跨否定辖域合并（如"没有重复。没有重复。"中若前句含否定修饰，不与其余句盲目合并而丢否定）。
5. **语义标点零改动**：`…/——/...` 等永不折叠；连续重复折叠**仅**作用于 `。！？.!?` 且 **≥3** 个。
6. **零回归硬契约**：`rules=None`（PRESETS 路径）输出与 v2.5 **字符串相等**；所有 v2.8 增强均 `explicit` 门控，绝不进入 `PRESETS`。

> 自检口诀：删后通读，若"模型该做什么"仍清晰、条件/否定/参数/代码俱在、单标点与语义标点完好，则通过。

---

## 7. 待确认问题 · 决议建议

1. **Q1 — 跨句重复的"重复"界定？完全子串匹配 vs 近义相似度**
   → 建议 v2.8 **仅做完全重复子串/整句（exact match）**；近义相似度（编辑距离/向量）留 P2/未来。理由：相似度易误伤"用不同表述强调同一要点"的合理重复，且实现成本高、风险大。
2. **Q2 — 同义堆叠识别范围？"总结/概述/归纳"是否去重**
   → 建议 v2.8 **仅做字面重复**；"总结一下，简单来说就是**总结**"中字面"总结"重复属 P0 范畴，而"总结/概述/归纳"同义词去重**不在本期**（见 §3 非目标）。避免同义词典误伤。
3. **Q3 — 标点压缩是否仅限 3+ 连续重复才折叠**
   → 建议 **是**（仅 ≥3 折叠）；`!!`/`??` 双连保留，保护强调语境不被误压。

> v2.8 关键边界（已决议·方案 B）：**P0-1 跨句去重采用新增独立 explicit-only 规则 id `duplicate_clauses`**（`explicit = (rules is not None)`，同 v2.7 `politeness` 扩展做法），**不改 `duplicate_lines` 语义**。原因——`duplicate_lines` 已属 `PRESETS`，若把跨句去重写进其恒生效分支将改变 `rules=None` 输出、破坏 `rules=None ≡ v2.5` 硬契约；方案 B 以全新 id 承载，契约天然安全。`duplicate_clauses` 与 `punctuation_compress` 两新 id 均**不进 `PRESETS`**，故 `rules=None` 输出零变化。
> - **方案 B（已采纳·team-lead 倾向）**：新增 `duplicate_clauses`（explicit-only）+ `punctuation_compress`（explicit-only），规则总数 11 → **13**。
> - **方案 A（回退备选）**：若 team-lead 最终定总数 12，则回退为不新增 id、跨句去重内嵌进 `_rule_duplicate_lines` 的 explicit 分支（需架构师补方案 A 修订设计）。

---

## 8. 落地改动清单（供架构师速览 · 仅描述变更）

- `skillforge/prompt_simplifier.py`：
  - `duplicate_lines`：**不改**（维持 v2.5 整行去重 base，恒生效）。
  - 新增 `duplicate_clauses` 规则类（**explicit-only，不进 `PRESETS`**）：`_DEDUP_CROSS_CLAUSE_THRESHOLD` 阈值常量 + `_rule_duplicate_clauses`（跨行/跨句完全重复子句去重，exact match，仅 `explicit=True` 生效）；注册进 `ALL_RULE_IDS` / `CANONICAL_ORDER` / `RULE_REGISTRY`。
  - 新增 `punctuation_compress` 规则类（**explicit-only，不进 `PRESETS`**）：`_PUNCT_COMPRESS_RE`（折叠 ≥3 连续 `。！？.!?`，排除 `…/——/...`/ASCII `...`），`_rule_punctuation_compress`；注册进 `ALL_RULE_IDS` / `CANONICAL_ORDER` / `RULE_REGISTRY`。
- `skillforge/__init__.py`：`__version__ = "2.8.0-evo"`。
- `frontend/app.js`：`SIMPLIFY_RULE_IDS` 追加 `"duplicate_clauses"`、`"punctuation_compress"`（共 **13** 类）；`duplicate_lines` 默认勾选态维持；两新 id 暴露策略见下。
- `frontend/index.html`：进阶精简分组新增 `data-rule="duplicate_clauses"` checkbox（P0，默认勾选，与跨句去重需求绑定）+ 可选新增 `data-rule="punctuation_compress"` checkbox（P1 低优先，可先不暴露 UI，仅留后端能力）。
- 测试（工程师任务）：
  - `tests/test_simplify_parity.py` 新增：`test_duplicate_clause_dedup_explicit_only`（断言 `rules=None` 路径**不**触发跨句去重、输出不变，守护 v2.5 契约）、`test_punctuation_compress_folds_triple`、`test_punctuation_compress_keeps_semantic`、`test_punctuation_compress_keeps_double`；`test_all_rule_ids_exact` 由 **11 → 13**。
  - 维持 `test_parity_balanced_rules_none_vs_v25` 绿（P0-3 零回归）。
