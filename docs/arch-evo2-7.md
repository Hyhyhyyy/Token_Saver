# 增量架构设计 · SkillForge 通用 Prompt 简化器（evo2-7 · 逻辑词/语气词过滤）

> 版本线：`2.6.0-evo` → `2.7.0-evo`
> 上游：基于 `docs/prd-evo2-7.md`（产品经理 Alice 交付）与现有 `skillforge/prompt_simplifier.py`（v2.6）设计。
> 本文件为**增量设计**，仅描述相对 v2.6 的**变更部分**；未提及的 v2.6 结构一律沿用。
> 契约硬约束：`rules is None` 后端路径逐字等于 v2.5（仅 5 基础类）；新类别**永不进入 `PRESETS`**。

---

## 1. 实现方案 + 框架选型

**框架选型**：沿用现有栈，**零新框架、零新 pip 依赖、前端零构建**。
- 后端：Python 标准库 `re` + 现有 `skillforge.tokenizer`（fastapi/uvicorn/pyyaml/tiktoken 已存在，无新增）。
- 前端：原生 HTML/CSS/JS（无打包、无框架），仅改常量与两个 checkbox。
- 架构模式：继续沿用 v2.6 的「规则注册表 + 预设 + 管道（protect → 按 `CANONICAL_ORDER` 串行执行 → restore）」。

**核心难点与裁定落地**：

1. **`explicit` 标志透传（落实主理人裁定）**
   - `simplify_prompt` 中 `explicit = (rules is not None)`。
   - 把 `explicit` 作为**第三个位置参数**透传给每个 `_rule_*(work, aggressive_like, explicit=False)`（默认 `False` 以兼容旧调用语义）。
   - `politeness` 的**扩展词表仅在 `explicit=True` 时叠加**；v2.5 原表（`_CN_FILLERS_BALANCED/_AGGRESSIVE` 等）**逐字不动** → `rules=None` 路径输出与 v2.5 字符串相等。

2. **新增 `_rule_logical_connector`（逻辑/序列/总结/过渡连接词）**
   - 仅移除不携带"要模型做什么"语义的连接词；**条件/控制流标记不纳入**（见 §3 `_CONDITIONAL_MARKERS`）。
   - **编号/有序列表语境保护**：行首为 `1.`/`第一、`/`(1)`/`步骤一`/`- 第…` 等有序列表标记时，行内序列词（`首先/其次/然后…`）**保护不删**。实现用**规则内局部哨兵 `\x01K<n>\x01`**（与外层 `\x00P/\x00K` 命名空间隔离，避免污染外层 `_restore`），删完再还原。
   - 复用 `_NEG_LOOKBEHIND` 否定前瞻，避免"不**因此**"→"不"。

3. **新增 `_rule_filler_particles`（句末/句中语气助词）**
   - 仅移除**句末**（后接 `。！？.!?…` 或文末）语气词；**句中谨慎不删**。
   - **`吗` 绝不纳入移除集**（保留疑问句意图，见 PRD Q4 → 本期默认不自动移除）。
   - 同样叠加 `_NEG_LOOKBEHIND` 满足硬约束 §6.4。

4. **强化 `politeness`（契约安全）**：扩展集（请单字/能否/帮我/辛苦了/拜托/劳驾/费心…）仅 `explicit=True` 叠加；单字「请」移除在 `aggressive_like or explicit` 时触发。
5. **强化 `hedging`（P1）**：补充多字安全词（应该/估计/想必/多半/八成/兴许/难免/基本上/大体上）。**刻意排除单字「应」**，避免误伤"应用/响应/答应"。

---

## 2. 文件列表（仅本次变更）

| 文件（相对 `skill-forge/`） | 变更类型 | 说明 |
|---|---|---|
| `skillforge/prompt_simplifier.py` | 修改 | 核心：签名加 `explicit`、新增两类规则+词典、注册、强化 politeness/hedging、去重 |
| `skillforge/__init__.py` | 修改 | `__version__ = "2.7.0-evo"` |
| `skillforge/server.py` | 修改(注释) | `/api/simplify` 契约确认无逻辑改动，仅补契约注释 |
| `frontend/app.js` | 修改 | `SIMPLIFY_RULE_IDS`+2、`SIMPLIFY_PRESETS` 重定义、默认勾选升级、`localStorage` key→`v2_7` 含 `v2_6` 迁移 |
| `frontend/index.html` | 修改 | 「进阶精简」分组新增两个 checkbox + 更新"保守"说明文字 |
| `frontend/style.css` | 修改 | 为两个新 checkbox 的辅助说明补极简样式（可选微调） |
| `tests/test_simplify_rules.py` | 修改 | `test_all_rule_ids_exact`→11；新增专项用例 |
| `tests/test_simplify_parity.py` | 修改 | **更新**过时的 `explicit base5 == preset` 断言（见 §5/§8） |
| `tests/test_simplify_evo27.py` | 新增 | 逻辑词/语气词/显式礼貌词专项回归（亦可并入上者） |
| `docs/arch-evo2-7.md` | 新增 | 本文件（架构师交付） |
| `docs/class-diagram-evo2-7.mermaid` | 新增 | 类/数据结构图 |
| `docs/sequence-diagram-evo2-7.mermaid` | 新增 | 调用时序图 |

---

## 3. 数据结构 / 接口变更

### 3.1 规则函数新签名（统一）

```python
# 旧：def _rule_xxx(work: str, aggressive_like: bool) -> tuple[str, int]
# 新：第三个参数 explicit，默认 False
def _rule_xxx(work: str, aggressive_like: bool, explicit: bool = False) -> tuple[str, int]:
    ...
```

主循环 `simplify_prompt` 中所有调用统一改为 `work, n = _rule_xxx(work, aggressive_like, explicit)`。

### 3.2 新增/调整的模块级常量（均在 `prompt_simplifier.py`）

```python
# —— 条件/控制流标记（硬排除，绝不进入 _LOGICAL_CONNECTORS）——
_CONDITIONAL_MARKERS = [
    "如果", "若", "假如", "假使", "一旦", "只要", "只有", "则", "那么",
    "否则", "除非", "不然", "要不然", "假若", "要是", "倘若",
]

# —— 逻辑连接词（草案，最终在定义处排除已属 _META_COMMENT 的词，避免重复计数）——
_LOGICAL_CONNECTORS_DRAFT = [
    # 因果
    "因此","所以","故","故此","故而","因而","于是","由此可见","正因如此","由此看来",
    # 转折
    "然而","但是","不过","可是","却","反倒","相反","与之相反","话虽如此","尽管如此",
    # 顺承/序列（有序列表行内受保护）
    "首先","其次","然后","接着","随后","最后","最终","一来","二来","再者","进而","与此同时",
    # 并列/增补
    "另外","此外","还有","另一方面","除此之外","以及","并且","同时",
    # 总结
    "总之","总而言之","总的来说","总的来讲","总的来看","综上","综上所述","一言以蔽之","概括地说",
    # 解释/强调
    "其实","事实上","实际上","具体来说","具体而言","换句话说","换言之","也就是说",
    "需要注意的是","值得一提的是","值得注意的是","明确地说","说白了","老实说","不瞒你说",
    # 话题
    "话说回来","言归正传","回到正题","顺便说一下","顺带一提","补充一下","多说一句","再说一句","再补充一点",
]
# 去重：排除已存在于 _META_COMMENT 的短语（保留 meta_comment 单独启用时的既有行为）
_LOGICAL_CONNECTORS = [w for w in _LOGICAL_CONNECTORS_DRAFT if w not in set(_META_COMMENT)]

# —— 句末语气助词（吗 刻意不纳入）——
_FILLER_PARTICLES = list("啊呢吧嘛呀哦啦哈嗯哟嘞咯呗呐嗷诶额呃咪噻捏哇耶喔喏啵")

# —— politeness 扩展集（仅 explicit=True 叠加；不含裸「请」，单字请由下方正则处理）——
_CN_FILLERS_EXPANDED = [
    "能否","可否","是否可以","可不可以","可以吗","行吗","好吗","方便吗",
    "不介意的话","如果可以的话","帮我","替我","辛苦了","费心","劳驾",
    "麻烦您","拜托你","求你","拜托","劳烦",
]

# —— hedging 强化（P1，仅追加多字安全词；不含单字「应」）——
_HEDGING += ["应该","估计","想必","多半","八成","兴许","难免","基本上","大体上"]

# —— 有序列表行识别（用于保护行内序列连接词）——
_ORDERED_LIST_LINE_RE = re.compile(
    r"^\s*(?:\d+[.、)）]|\(\d+\)|第[一二三四五六七八九十百零\d]+[、.、]|"
    r"[-*•+]\s*第|步骤[一二三四五六七八九十百零\d]+)"
)
```

> 注意 `_META_COMMENT` **保持不变**（不去重它，而是让 `_LOGICAL_CONNECTORS` 排除其成员）。这样：
> - 仅启用 `meta_comment` → 行为同 v2.6（无回归）；
> - 仅启用 `logical_connector` → 移除其独有连接词；
> - 两者同启（前端"保守"默认如此）→ 并集覆盖，无重复计数。

### 3.3 注册表 / 单一真源变更

```python
ALL_RULE_IDS = [
    "politeness","role_prefix","empty_items","duplicate_lines","blank_lines",
    "meta_comment","hedging","redundant_adverbs","examples_trim",
    "logical_connector","filler_particles",   # ← +2
]

CANONICAL_ORDER = [
    "empty_items","duplicate_lines","blank_lines",
    "politeness","role_prefix",
    "meta_comment","hedging","redundant_adverbs","examples_trim",
    "logical_connector","filler_particles",    # ← 追加到末尾（不破坏前 5 位与 v2.5 一致的顺序）
]

# PRESETS 不变（仍仅 5 基础类，保障 rules=None ≡ v2.5）

RULE_REGISTRY = {
    ...原 9 项...,
    "logical_connector": {"fn": _rule_logical_connector, "default_in_presets": False},
    "filler_particles":  {"fn": _rule_filler_particles,  "default_in_presets": False},
}
```

### 3.4 `_rule_politeness` 关键改动（explicit 叠加）

```python
def _rule_politeness(work, aggressive_like, explicit=False):
    cn_fillers = list(_CN_FILLERS_BALANCED)
    en_fillers = list(_EN_FILLERS_BALANCED)
    if aggressive_like:
        cn_fillers += _CN_FILLERS_AGGRESSIVE
        en_fillers += _EN_FILLERS_AGGRESSIVE
    if explicit:                      # ← 仅显式路径叠加扩展集
        cn_fillers += _CN_FILLERS_EXPANDED
    # ... 原移除逻辑不变 ...
    if aggressive_like or explicit:   # ← 单字「请」在显式路径也移除（实现"默认更强"）
        cnt = len(re.findall(r"请(?=[一-鿿])", work))
        if cnt:
            work = re.sub(r"请(?=[一-鿿])", "", work)
            filler_removed += cnt
    return work, filler_removed
```

### 3.5 前端常量新值（`frontend/app.js`）

```javascript
const SIMPLIFY_RULE_IDS = [
  "politeness","role_prefix","empty_items","duplicate_lines","blank_lines",
  "meta_comment","hedging","redundant_adverbs","examples_trim",
  "logical_connector","filler_particles",   // +2
];

// 保守 = 5 基础 + logical_connector + filler_particles + meta_comment（默认更强）
// 激进 = 保守 + hedging + redundant_adverbs + examples_trim（全 11 类）
const SIMPLIFY_PRESETS = {
  balanced:   { mode: "balanced",   rules: ["politeness","role_prefix","empty_items","duplicate_lines","blank_lines","meta_comment","logical_connector","filler_particles"] },
  aggressive: { mode: "aggressive", rules: ["politeness","role_prefix","empty_items","duplicate_lines","blank_lines","meta_comment","hedging","redundant_adverbs","examples_trim","logical_connector","filler_particles"] },
};
```

`localStorage` key：`"skillforge_simplify_v2_7"`；`loadSimplifyState` 先读 `v2_7`，缺失再读 `v2_6`（迁移：用仍存在 id 过滤后应用并写回 `v2_7`），再缺失则用新默认（即"保守"预设）。

---

## 4. 程序调用流程（时序）

主流程：`explicit` 透传 + protect 顺序（详见 `docs/sequence-diagram-evo2-7.mermaid`）。

1. 前端 `doSimplify` 始终下发 `{text, mode, rules}`（`rules` 为当前勾选集合，非空）→ 后端 `explicit=True`。
2. `server.py /api/simplify`：`rules` 非 list → `None`（契约兜底）；否则透传。
3. `simplify_prompt(text, mode, rules)`：
   - `explicit = rules is not None`
   - `_resolve_rule_ids` → `(rule_ids, mode_used, aggressive_like)`（`rules=None` 走 `PRESETS` = 5 基础类）
   - `_protect`：冻结 fenced/行内代码、URL（`\x00P\x00`）+ 安全词（`\x00K\x00`）
   - 按 `CANONICAL_ORDER` 顺序，仅对 `id in rule_ids` 的规则调用 `_rule_*(work, aggressive_like, explicit)`
   - `_restore` 还原保护片段 → 统计 token → 返回 `dict`
4. `rules=None` 路径：`explicit=False`，`PRESETS` 仅 5 基础类，`politeness` 不叠加扩展集、不删单字「请」（balanced）→ 输出逐字等于 v2.5。
5. 显式路径：`explicit=True` → `logical_connector`/`filler_particles` 生效；`politeness` 叠加扩展集；`hedging` 用强化表。

> **protect 顺序要点**：protect 在规则执行**前**一次性完成；新规则作用在被保护片段**之外**的文本；编号列表内的序列词保护由 `_rule_logical_connector` 用**局部 `\x01K\x01` 哨兵**在规则内自包含完成，不污染外层 `_restore` 的 `\x00` 命名空间。

---

## 5. 任务列表（有序、含依赖，给工程师）

> 共 **4** 个任务。T01 为基础设施/契约基线（类比"项目基础设施"任务，确认零新增依赖+版本+入口契约）；T02/T03 可并行；T04 收尾文档。

### T01 · P0 · 基础设施与契约基线
- **Source Files**：`requirements.txt`、`skillforge/__init__.py`、`skillforge/server.py`
- **Dependencies**：无
- **内容**：
  1. `requirements.txt`：补注释确认 evo2-7 **零新增运行时依赖**。
  2. `__init__.py`：`__version__ = "2.7.0-evo"`。
  3. `server.py`：`/api/simplify` 补契约注释（`rules` 非 list→`None` 兜底；新类别不影响 `rules=None` 路径），**无逻辑改动**。

### T02 · P0 · 后端规则引擎增量 + 测试
- **Source Files**：`skillforge/prompt_simplifier.py`、`tests/test_simplify_rules.py`、`tests/test_simplify_parity.py`、`tests/test_simplify_evo27.py`
- **Dependencies**：T01
- **内容**：
  1. `_rule_*` 统一加 `explicit: bool = False` 第三参数；主循环透传。
  2. 新增 `_LOGICAL_CONNECTORS`（排除 `_META_COMMENT` 成员）、`_FILLER_PARTICLES`、`_CN_FILLERS_EXPANDED`、`_HEDGING` 追加、`_CONDITIONAL_MARKERS`、`_ORDERED_LIST_LINE_RE`。
  3. 实现 `_rule_logical_connector`（局部 `\x01K\x01` 保护有序列表序列词 + 否定前瞻移除连接词）、`_rule_filler_particles`（句末+否定前瞻+排除`吗`）。
  4. 强化 `_rule_politeness`（explicit 叠加扩展集 + 单字请）、`_rule_hedging`（`_HEDGING +=` 多字安全词）。
  5. `ALL_RULE_IDS`/`CANONICAL_ORDER`/`RULE_REGISTRY` 增两项；`PRESETS` 不变。
  6. 更新 `test_all_rule_ids_exact`（→11）、**修改 `test_parity_explicit_base5_matches_preset`**（该断言在 explicit 扩展契约下已失效，改为断言 `rules=None` 仍逐字等于 v2.5 + 新增 `test_politeness_explicit_only` 说明 explicit 扩展差异）；保留 `test_parity_balanced_rules_none_vs_v25`/`test_parity_aggressive_not_weaker_than_v25`（必须全绿）。
  7. 新增 `test_simplify_evo27.py`：`test_logical_connector_keeps_instructions`、`test_logical_connector_protects_conditional_and_ordered_list`、`test_filler_particles_safe`（保留`吗`/句末移除/句中不删）、`test_politeness_explicit_only`、`test_hedging_strengthened`（P1）。

### T03 · P0 · 前端简化器 UI 与默认态
- **Source Files**：`frontend/app.js`、`frontend/index.html`、`frontend/style.css`
- **Dependencies**：无（与 T01/T02 并行；后端契约稳定）
- **内容**：
  1. `app.js`：`SIMPLIFY_RULE_IDS`+2、`SIMPLIFY_PRESETS` 按 §3.5 重定义；`loadSimplifyState` 改读 `skillforge_simplify_v2_7`，缺失回退 `v2_6` 迁移；`saveSimplifyState` 写 `v2_7`；默认进入应用"保守"预设（含两新类）。
  2. `index.html`：「进阶精简」分组新增 `data-rule="logical_connector"`/`data-rule="filler_particles"` 两个 checkbox；更新"保守=安全无损（v2.5 等价）"说明为"保守=默认更强（已含逻辑词/语气词过滤）"。
  3. `style.css`：为新 checkbox 辅助说明补极简样式（如 `.chk .hint`）。

### T04 · P1 · 文档与跨文件约定同步
- **Source Files**：`docs/arch-evo2-7.md`、`README.md`、`docs/class-diagram-evo2-7.mermaid`、`docs/sequence-diagram-evo2-7.mermaid`
- **Dependencies**：T01、T02、T03
- **内容**：本文件定稿；`README.md` 简化器说明补充两新类与"默认更强"策略；抽取类图/时序图到对应 `.mermaid`（见随附文件）。

---

## 6. 依赖包列表（新增）

**无新增。** 运行时仍仅 `fastapi` / `uvicorn` / `pyyaml` / `tiktoken`（及 Python 标准库）。前端零构建。

---

## 7. 共享知识（跨文件约定）

- **规则 id 单一真源**：后端 `ALL_RULE_IDS` 与前端 `SIMPLIFY_RULE_IDS` **必须逐字一致**；任一侧增删需同步。
- **保护占位符命名空间**：
  - 外层（跨规则共享）：`\x00P<n>\x00`（代码/URL/行内代码）、`\x00K<n>\x00`（安全词），由 `_protect/_protect_words/_restore` 统一维护。
  - 规则内局部哨兵（如有序列表序列词保护）：用 `\x01K<n>\x01` 等 **`\x01` 命名空间**，避免与外层 `\x00` 冲突、污染 `_restore`。
- **否定前瞻**：`_NEG_LOOKBEHIND`（`不没别未无莫非勿`，覆盖 0~2 字前导）为共享原语，应用于 `logical_connector` / `filler_particles` / `hedging` / `redundant_adverbs`。
- **词典常量位置**：所有词表集中在 `prompt_simplifier.py` 模块级；条件标记 `_CONDITIONAL_MARKERS` 仅作文档/防护参考，**不得**进入 `_LOGICAL_CONNECTORS`。
- **`explicit` 语义**：`explicit = (rules is not None)`；仅此标志控制"扩展词表叠加 / 单字请移除 / 新类别生效"，`rules=None` 永远等价 v2.5。
- **`localStorage`**：key `skillforge_simplify_v2_7`；`v2_6` 仅作一次性迁移源。
- **变更标签**：`_tag(change, category, explicit)` 仅在 `explicit=True` 时附加 `[category]`，保障 `rules=None` 纯文本格式（parity 关键）。

---

## 8. 待明确事项 / 风险提示

1. **⚠ 必改的回归测试（关键）**：v2.6 的 `test_parity_explicit_base5_matches_preset` 在"explicit 扩展 politeness"契约下**不再成立**（显式 base5 会比 `rules=None` 多删礼貌词）。必须按 T02 修改该断言，否则 CI 红。硬契约只剩 `rules=None ≡ v2.5`（`test_parity_balanced_rules_none_vs_v25` 须全绿）。
2. **`meta_comment` 与 `logical_connector` 去重策略**：本设计选"保持 `_META_COMMENT` 不变、`_LOGICAL_CONNECTORS` 排除其成员"。若团队更希望反向（把过渡词全部迁到 `logical_connector` 并从 `meta_comment` 删除），需在 T02 同步调整并回归，但会改 `meta_comment` 单独启用时的行为——当前方案零回归，推荐维持。
3. **单字「应」排除**：`hedging` 强化**不含**裸「应」，仅用多字「应该」等，以防误伤"应用/响应/答应"。如确需更激进，单列评估。
4. **句末 `吗`**：本期默认**不自动移除**（保留疑问句）。若后续纳入，须满足 PRD Q4 的"仅句末 `吗？`/`吗。` 且前接非关键疑问词"条件——本期不实现。
5. **英文 filler（um/uh/you know…）**：属 PRD P2-1，本期**不实现**，留待下版。
6. **Q2 编号列表保护**：已落实为"有序列表行内序列词保护"（T02 `_rule_logical_connector`）。非列表游离文本中的序列词仍正常移除。
