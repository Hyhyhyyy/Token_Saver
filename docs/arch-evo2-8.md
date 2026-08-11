# 增量架构设计 · SkillForge 通用 Prompt 简化器（evo2-8 · token 用量维度优化）

> 版本线：`2.7.0-evo` → `2.8.0-evo`
> 上游：基于 `docs/prd-evo2-8.md`（产品经理 Alice 交付）与现有 `skillforge/prompt_simplifier.py`（已含 v2.7 的 `explicit` 透传、`logical_connector`/`filler_particles` 两新规则、`duplicate_lines` 保持 v2.5 原状）。
> 本文件为**增量设计**，仅描述相对 v2.7 的**变更部分**；未提及的 v2.7 结构一律沿用。
> 契约硬约束：`rules is None` 后端路径逐字等于 v2.5（仅 5 基础类）；任何 v2.8 新增/增强行为不得改变该路径输出。

---

## 1. 实现方案 + 框架选型

**框架选型**：沿用现有栈，**零新框架、零新 pip 依赖、前端零构建**（同 v2.7）。
- 后端：Python 标准库 `re` + 现有 `skillforge.tokenizer`（fastapi/uvicorn/pyyaml/tiktoken 已存在，无新增）。
- 前端：原生 HTML/CSS/JS，仅改常量与两个 checkbox。
- 架构模式：继续沿用「规则注册表（`RULE_REGISTRY`）+ 预设（`PRESETS`）+ 管道（protect → 按 `CANONICAL_ORDER` 串行执行 → restore）」，`explicit = (rules is not None)` 已实现并透传，本版复用。

**两大变更**：
1. **P0 跨句/跨句完全重复子句去重** → 采用**方案 B**（独立 explicit-only 规则 id `duplicate_clauses`，不进 `PRESETS`）。理由：边界最清晰、`duplicate_lines` 语义零改动、`rules=None` 由"结构性不进 PRESETS"天然零回归（无需任何 special-case）。
2. **P1 连续重复标点折叠** → 新增 `punctuation_compress` 规则（不进 `PRESETS`，前端默认勾选）。

---

## 2. 文件列表（仅本次变更）

| 文件（相对 `skill-forge/`） | 变更类型 | 说明 |
|---|---|---|
| `skillforge/prompt_simplifier.py` | 修改 | 新增 `_rule_duplicate_clauses` + `_rule_punctuation_compress`；注册两新 id；`ALL_RULE_IDS`/`CANONICAL_ORDER` +2；常量 `_PUNCT_FOLD_RE`/`_DUP_CLAUSE_*`；`duplicate_lines` 不动 |
| `skillforge/__init__.py` | 修改 | `__version__ = "2.8.0-evo"` |
| `skillforge/server.py` | 修改(注释) | `/api/simplify` 契约确认无逻辑改动，补 v2.8 注释 |
| `frontend/app.js` | 修改 | `SIMPLIFY_RULE_IDS` 11→**13**；`SIMPLIFY_PRESETS` 调整（两新类进 保守 默认勾选）；`localStorage` key 升 `v2_8` 并迁移 `v2_7` |
| `frontend/index.html` | 修改 | 「进阶精简」分组新增 `data-rule="duplicate_clauses"` / `data-rule="punctuation_compress"` 两个 checkbox |
| `frontend/style.css` | 修改 | 为新 checkbox 辅助说明补极简样式（可选微调） |
| `tests/test_simplify_rules.py` | 修改 | `test_all_rule_ids_exact`→**13**；新增 `duplicate_clauses` / `punctuation_compress` 专项用例 |
| `tests/test_simplify_parity.py` | 修改/新增 | 新增 `test_duplicate_clause_dedup_explicit_only` / `test_punctuation_compress_*`；维持 `test_parity_balanced_rules_none_vs_v25` 绿 |
| `docs/arch-evo2-8.md` | 新增 | 本文件（架构师交付） |
| `docs/class-diagram-evo2-8.mermaid` | 新增 | 类/数据结构图 |
| `docs/sequence-diagram-evo2-8.mermaid` | 新增 | 调用时序图 |

> ⚠ **计数更正（重要）**：PRD §8 与 team-lead 任务清单写"SIMPLIFY_RULE_IDS 11→12"，但**方案 B 引入 `duplicate_clauses` 这一独立新 id，叠加 `punctuation_compress` 共 +2 个 id**，故正确总数是 **11 → 13**（非 12）。本设计按方案 B 落实，并建议 PM 将 PRD §8 的"共 12 类"更正为"共 13 类"、`test_all_rule_ids_exact` 断言改为 13。若团队坚持总数为 12，则必须回退到方案 A（不新增 id，跨句去重内嵌进 `duplicate_lines` 的 explicit 分支）。

---

## 3. 数据结构 / 接口变更

### 3.1 决策：方案 B（独立 `duplicate_clauses` explicit-only id）

- `duplicate_lines` **逐字保持 v2.5 行为**（行级归一化去重，恒生效，继续在 `PRESETS` 中）。
- 新增 `_rule_duplicate_clauses(work, aggressive_like, explicit=False)`：跨句/跨句字面完全重复子句去重。它**不进 `PRESETS`**，因此 `rules=None` 路径永远不会包含它 → `rules=None ≡ v2.5` 由结构保证，零回归最稳。
- 前端 `SIMPLIFY_RULE_IDS` 必须与后端 `ALL_RULE_IDS` 逐字一致（既有约定），故 `duplicate_clauses` 必入前端数组 → 总数 13。

### 3.2 `ALL_RULE_IDS` / `CANONICAL_ORDER`（各 +2，共 13）

```python
ALL_RULE_IDS: list[str] = [
    "politeness", "role_prefix", "empty_items", "duplicate_lines",
    "duplicate_clauses",          # ← 新增（方案 B，explicit-only）
    "blank_lines", "meta_comment", "hedging", "redundant_adverbs", "examples_trim",
    "logical_connector", "filler_particles",
    "punctuation_compress",       # ← 新增（P1，explicit-only）
]

CANONICAL_ORDER: list[str] = [
    "empty_items", "duplicate_lines", "duplicate_clauses", "blank_lines",
    "politeness", "role_prefix",
    "meta_comment", "hedging", "redundant_adverbs", "examples_trim",
    "logical_connector", "filler_particles", "punctuation_compress",
]
# 说明：前 5 位（含 duplicate_lines）与 v2.5 执行顺序逐字一致；
# duplicate_clauses 紧贴 duplicate_lines（同属去重族）；punctuation_compress 置末。
# PRESETS 不变（仍仅 5 基础类）。
```

### 3.3 新增规则注册

```python
RULE_REGISTRY = {
    ...原 11 项...,
    "duplicate_clauses":   {"fn": _rule_duplicate_clauses,   "default_in_presets": False},
    "punctuation_compress":{"fn": _rule_punctuation_compress,"default_in_presets": False},
}
```

### 3.4 新增常量（模块级，集中于 `prompt_simplifier.py`）

```python
# —— P0 跨句/跨句完全重复子句去重（方案 B；explicit-only）——
_DUP_CLAUSE_MIN_LEN = 4          # 非句末子句重复的最小 CJK 字符数（阈值护栏）
# 句末标点（用于切分句子 / 判定"整句重复"与"句末冗余尾词"）
_SENT_END_RE = re.compile(r"[。！？]")

# —— P1 连续重复标点折叠（explicit-only；不进 PRESETS）——
# 折叠集 = CJK 。！？ + ASCII ! ?；**刻意排除 ASCII `.`**，以保护语义省略号 `...`
# （`……` U+2026 / `——` U+2014 本就不在集内，天然排除）。
_PUNCT_FOLD_RE = re.compile(r"([。！？!?])\1{2,}")   # 3+ 同字符 → 单字符
```

### 3.5 `punctuation_compress` 关键设计

```python
def _rule_punctuation_compress(work, aggressive_like=False, explicit=False):
    """折叠 3+ 连续 。！？.!? → 单；排除 …/——/ASCII ...；不进 PRESETS。"""
    # 受保护 token（\x00P..\x00 / \x00K..\x00）内标点已冻结为占位符，正则不会跨入。
    new, n = _PUNCT_FOLD_RE.subn(r"\1", work)
    return new, n
```
- `！！！`→`！`、`？？？`→`？`、`。。。 `→`。`；`!!`/`??`/`。。` 仅 2 个→不折叠（保留强调）。
- `……`（U+2026×2）、`——`（U+2014×2）、`...`（ASCII 点×3，因 `.` 不在折叠集）→均**原样保留**。
- 代码/行内代码/URL 内 `???` 受 `_protect` 冻结 → 不被触碰。

### 3.6 `duplicate_clauses` 算法（设计级，不写实现代码）

**目标**：删除跨句/跨句的**字面完全重复子句**（identical substring / 整句），绝不靠相似度。

**护栏（硬约束 §6）**：
1. **仅 exact match**：用不同表述强调同一要点（近义）天然不触（本版不做同义归并）。
2. **阈值判定（架构师拍板，解决 PRD §5/§7 边界冲突）**：一个重复单元 U 被删除当且仅当满足以下**任一**：
   - (a) **整句重复**：U 是以 `。！？` 收尾的整句，且在前文逐字出现 → 删后副本（保留前副本）。
   - (b) **长重复子句**：`len(U) ≥ _DUP_CLAUSE_MIN_LEN`（≥4 汉字）且作为 exact substring 出现 ≥2 次 → 删一个副本。
   - (c) **句末冗余尾词**：U 是 ≥2 字的有界 CJK 词，出现 ≥2 次且**至少一次紧邻句末标点 `。！？` 或文末**（如"…简单来说就是**总结**。"）→ 删该句末副本。
   - **且** U 的两副本**非紧邻重叠**（排除"非常非常"这类叠词强调，见下）。
3. **保护共享动词非完全重复**："删除 config.py 中的 retry 配置。删除 output.log 中的错误行。"——两句仅共享前两字"删除"，后续上下文不同 → 不满足 (a)/(b)/(c)（"删除"非句末、长度 2<阈值、且不构成整句/长重复）→ **不误并**。
4. **保护叠词强调**："非常非常重要"中"非常"两副本**紧邻重叠**（AA 型）→ 触发 (2) 的"非紧邻"排除 → 不删。
5. **保护代码/URL**：在受保护 token 之外运算；按 `\x00..\x00` 占位符切分为非保护片段，仅在片段内做跨句去重，绝不跨代码块误并。
6. **否定/条件不丢**：保留一个完整副本即可（删的是冗余副本，保留副本自带其否定/条件语义），不会"盲目合并而丢否定"。

> 该阈值三分支（整句 / 长重复 / 句末尾词）+ 非紧邻排除，是**同时满足 PRD §5 全部 P0-1 样例**（整行重复、跨句子句、字面"总结"尾词、保护共享动词、保护代码、保护短重复）与硬约束 §6 的唯一一致解。

### 3.7 前端常量新值（`frontend/app.js`）

```javascript
const SIMPLIFY_RULE_IDS = [
  "politeness","role_prefix","empty_items","duplicate_lines","duplicate_clauses",
  "blank_lines","meta_comment","hedging","redundant_adverbs","examples_trim",
  "logical_connector","filler_particles","punctuation_compress",   // +2 → 13
];

// 保守 = 5 基础 + meta_comment + logical_connector + filler_particles
//        + duplicate_clauses + punctuation_compress（默认更强，两新类均默认勾选）
// 激进 = 保守 + hedging + redundant_adverbs + examples_trim（全 13 类）
const SIMPLIFY_PRESETS = {
  balanced:   { mode: "balanced",   rules: ["politeness","role_prefix","empty_items","duplicate_lines","duplicate_clauses","blank_lines","meta_comment","logical_connector","filler_particles","punctuation_compress"] },
  aggressive: { mode: "aggressive", rules: ["politeness","role_prefix","empty_items","duplicate_lines","duplicate_clauses","blank_lines","meta_comment","hedging","redundant_adverbs","examples_trim","logical_connector","filler_particles","punctuation_compress"] },
};
```

`localStorage` key 沿用 v2.7 约定升级：`"skillforge_simplify_v2_8"`；`loadSimplifyState` 优先读 `v2_8`，缺失回退 `v2_7`（用仍存在的 id 过滤后应用并写回 `v2_8`），再缺失则用新默认（即"保守"预设）。`saveSimplifyState` 写 `v2_8`。

---

## 4. 程序调用流程（时序）

主流程：`explicit` 透传 + protect 顺序（详见 `docs/sequence-diagram-evo2-8.mermaid`）。

1. 前端 `doSimplify` 始终下发 `{text, mode, rules}`（`rules` 为当前勾选集合，含两新类时非空）→ 后端 `explicit=True`。
2. `server.py /api/simplify`：`rules` 非 list → `None`（契约兜底）；否则透传。
3. `simplify_prompt(text, mode, rules)`：
   - `explicit = rules is not None`；`_resolve_rule_ids` → `(rule_ids, mode_used, aggressive_like)`（`rules=None` 走 `PRESETS` = 5 基础类，**绝不含 `duplicate_clauses`/`punctuation_compress`**）。
   - `_protect`：冻结 fenced/行内代码、URL（`\x00P\x00`）+ 安全词（`\x00K\x00`）。
   - 按 `CANONICAL_ORDER` 顺序，仅对 `id in rule_ids` 的规则调用 `_rule_*(work, aggressive_like, explicit)`：
     - `empty_items` → `duplicate_lines`（v2.5 行为不变）→ **`duplicate_clauses`**（仅当显式勾选时存在）→ `blank_lines`（首折）→ `politeness` → `role_prefix` → 其余 v2.6/v2.7 类 → `logical_connector` → `filler_particles` → **`punctuation_compress`**（末）。
   - `_restore` 还原保护片段 → 统计 token → 返回 `dict`。
4. `rules=None` 路径：`explicit=False`，`PRESETS` 仅 5 基础类，`duplicate_clauses`/`punctuation_compress` 永不运行 → 输出逐字等于 v2.5。

---

## 5. 任务列表（有序、含依赖，给工程师）

> 共 **4** 个任务。T01 为基础设施/契约基线；T02/T03 可并行；T04 收尾文档。

### T01 · P0 · 基础设施与契约基线
- **Source Files**：`requirements.txt`、`skillforge/__init__.py`、`skillforge/server.py`
- **Dependencies**：无
- **内容**：
  1. `requirements.txt`：补注释确认 evo2-8 **零新增运行时依赖**。
  2. `__init__.py`：`__version__ = "2.8.0-evo"`。
  3. `server.py`：`/api/simplify` 补 v2.8 契约注释（`rules` 非 list→`None` 兜底；两新类不影响 `rules=None` 路径），**无逻辑改动**。

### T02 · P0 · 后端规则引擎增量 + 测试
- **Source Files**：`skillforge/prompt_simplifier.py`、`tests/test_simplify_rules.py`、`tests/test_simplify_parity.py`
- **Dependencies**：T01
- **内容**：
  1. 新增常量 `_DUP_CLAUSE_MIN_LEN`、`_SENT_END_RE`、`_PUNCT_FOLD_RE`（折叠集**排除 ASCII `.`**）。
  2. 实现 `_rule_duplicate_clauses`（§3.6 三分支阈值 + 非紧邻排除 + 保护片段外运算）；`duplicate_lines` **不动**。
  3. 实现 `_rule_punctuation_compress`（`_PUNCT_FOLD_RE.subn`，3+ 同字符折叠）。
  4. `ALL_RULE_IDS`/`CANONICAL_ORDER` 增两项（`duplicate_clauses` 紧邻 `duplicate_lines`，`punctuation_compress` 置末）；`RULE_REGISTRY` 增两项；`PRESETS` 不变。
  5. `simplify_prompt` 主循环：在 `duplicate_lines` 后插入 `duplicate_clauses` 分支、在 `filler_particles` 后插入 `punctuation_compress` 分支（均 `_tag(..., explicit)`）。
  6. 测试：`test_all_rule_ids_exact` 改为 **13**；新增 `test_duplicate_clause_dedup_explicit_only`（断言 `rules=None` 不触发、输出不变）、`test_duplicate_clause_keeps_shared_verb`、`test_duplicate_clause_terminal_word`（"总结一下，简单来说就是总结。"→"总结一下，简单来说就是。"）、`test_duplicate_clause_whole_sentence`（"请确保输出 JSON。请确保输出 JSON 并校验字段。"→"请确保输出 JSON。并校验字段。"）、`test_punctuation_compress_folds_triple`（`？？？`/`！！！`/`。。。 `）、`test_punctuation_compress_keeps_semantic`（`……`/`——`）、`test_punctuation_compress_keeps_double`（`!!`）、`test_punctuation_compress_keeps_code`。保留 `test_parity_balanced_rules_none_vs_v25` / `test_parity_aggressive_not_weaker_than_v25` / `test_parity_explicit_base5_politeness_expansion`（必须全绿）。

### T03 · P0 · 前端简化器 UI 与默认态
- **Source Files**：`frontend/app.js`、`frontend/index.html`、`frontend/style.css`
- **Dependencies**：无（与 T01/T02 并行；后端契约稳定）
- **内容**：
  1. `app.js`：`SIMPLIFY_RULE_IDS`→13（加 `duplicate_clauses`/`punctuation_compress`）；`SIMPLIFY_PRESETS` 按 §3.7 重定义（两新类进 保守 默认勾选）；`loadSimplifyState` 改读 `skillforge_simplify_v2_8`，缺失回退 `v2_7` 迁移；`saveSimplifyState` 写 `v2_8`。
  2. `index.html`：「进阶精简」分组新增 `data-rule="duplicate_clauses"`、`data-rule="punctuation_compress"` 两个 checkbox。
  3. `style.css`：为新 checkbox 辅助说明补极简样式（如 `.chk .hint`）。

### T04 · P1 · 文档与跨文件约定同步
- **Source Files**：`docs/arch-evo2-8.md`、`README.md`、`docs/class-diagram-evo2-8.mermaid`、`docs/sequence-diagram-evo2-8.mermaid`
- **Dependencies**：T01、T02、T03
- **内容**：本文件定稿；`README.md` 简化器说明补充两新类与"默认更强"策略；抽取类图/时序图到对应 `.mermaid`（见随附文件）。

---

## 6. 依赖包列表（新增）

**无新增。** 运行时仍仅 `fastapi` / `uvicorn` / `pyyaml` / `tiktoken`（及 Python 标准库）。前端零构建。

---

## 7. 共享知识（跨文件约定）

- **规则 id 单一真源**：后端 `ALL_RULE_IDS` 与前端 `SIMPLIFY_RULE_IDS` **必须逐字一致**（现 13 项）；任一侧增删需同步。
- **`explicit` 语义**：`explicit = (rules is not None)`；`duplicate_clauses`/`punctuation_compress` 仅因"不进 `PRESETS`"而天然 explicit-only，`rules=None` 永不触发。
- **保护占位符命名空间**：外层 `\x00P\x00`/`\x00K\x00`（跨规则共享）；规则内局部哨兵 `\x01K\x01`（v2.7 有序列表序列词保护）。`duplicate_clauses` 须在**非保护片段内**运算（按 `\x00..\x00` 切分），避免跨代码块误并。
- **标点折叠集**：`_PUNCT_FOLD_RE` 用 `[。！？!?]`（**不含 ASCII `.`**），以同时满足"折叠 3+ 同字符"与"保留 `...`/`……`/`——`"。
- **`localStorage`**：key `skillforge_simplify_v2_8`；`v2_7` 仅作一次性迁移源（沿用 v2.7 约定）。
- **变更标签**：`_tag(change, category, explicit)` 仅在 `explicit=True` 时附加 `[category]`，保障 `rules=None` 纯文本格式。

---

## 8. 待明确事项 / 风险提示

1. **⚠ 计数更正（必改）**：方案 B 使 `ALL_RULE_IDS` 为 **13**（非 PRD §8 / 任务清单所写 12）。请 PM 将 PRD §8 "共 12 类" 更正为 "共 13 类"，并将 `test_all_rule_ids_exact` 断言改为 13。若坚持 12，则须回退方案 A（不新增 id）。**本设计已按 B=13 落实。**
2. **`duplicate_clauses` 阈值三分支**（§3.6）是 PRD §5/§7 边界冲突的唯一一致解：整句重复 / ≥4 字长重复 / 句末冗余尾词 + 非紧邻排除。建议在 T02 落地后用 §5 全部 P0-1 样例做回归锁定；若产品希望更激进（如降低 `_DUP_CLAUSE_MIN_LEN` 或允许跨相邻），单列评估。
3. **标点折叠仅同字符 3+**（`\1{2,}`）：混合 `？！？` 不折叠（保留强调/语气）。若产品希望"任意 3+ 连续 。！？.!? 不论是否同字符"也折叠，需改正则为 `(?:[。！？!?]){3,}`，单列评估。
4. **`duplicate_clauses` 前端默认勾选**：本设计将其与 `punctuation_compress` 一并纳入 保守 预设（默认更强）。若团队认为 P0 去重过于激进不宜默认开启，可仅保留 `punctuation_compress` 默认勾选、`duplicate_clauses` 仅作可选 checkbox——单列评估。
5. **近义/同义归并、通顺化、英文 filler 变体**：均为 PRD §3 非目标 / 未来方向，本期不做。
