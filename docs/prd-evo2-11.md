# PRD · SkillForge 通用 Prompt 简化器（增量 evo2-11 · 规则规范化）

> 版本线：2.10-evo → 2.11-evo（版本号由主理人处理 `__init__`，本增量仅出分析与文档，不改源码）。
> 范围**仅**限「通用 Prompt 简化器」：`prompt_simplifier.py` / `/api/simplify` / 前端「简化」视图。**不**动 `cleaner.py` / SKILL.md 清洗。
> 本增量**叠加于 v2.10 之上**：v2.10 的 15 类规则、`PRESETS`（5 基础类）、保护机制、`explicit = (rules is not None)` 契约一律沿用，不推翻。
> 硬契约（不可破坏）：`rules is None` 时后端走 `PRESETS`，其 `simplified_text` 必须**逐字等于 v2.5**（仅那 5 个基础类）。**任何 v2.11 新增行为不得改变该路径输出。**
> 零新增 pip 运行时依赖：仅 Python 标准库 + 现有 `tokenizer` / `scorer`。

---

## ① 产品目标

- **G1（模式可感知差异）**：让「保守 / 激进」两种模式在**类别集合**与**每条规则命中深度**两个层面都有用户一眼可辨的差异，彻底解决"看不出强化模式和保守模式的区别"。
- **G2（消除自指冗余）**：既然 prompt 天然是"我向模型提需求"，应系统性去除第一人称自指 / 客套受益标记（给我 / 和我 / 为我 / 由我 / 依我看 / 我想 / 我希望 / 请帮我…），而不仅是零散几个词。
- **G3（规则可枚举 · 可解释 · 可防护）**：把现有 15 条规则的筛选标准**逐条规范化、深化**，全部枚举展示；每条都有明确边界、否定护栏与保护集，杜绝"凭感觉删词"。

---

## ② 用户故事

- US-1（作为提示词作者）：切换「保守 ↔ 激进」时，我希望在**同一段输入**上看到明显不同的输出（激进会多删自指、弱语气、连接词等），而不是几乎一样。
- US-2（作为提示词作者）：我希望"请**给我**写个爬虫""**和我**确认下日程"里的"给我/和我"这类默认冗余自指标记被清掉，不必我手动改。
- US-3（作为审阅者）：我希望前端能把**每一条规则的筛选标准、命中示例、保留边界**完整列出来，让我知道什么会被删、什么不会。

---

## ③ 现状核实（已读代码，非臆测）

> 以下结论均来自 `skillforge/prompt_simplifier.py`（第 42–273 行常量表、`RULE_REGISTRY`、`PRESETS`、`CANONICAL_ORDER` 与 15 条规则实现）与 `frontend/app.js` 的 `SIMPLIFY_RULE_IDS` / `SIMPLIFY_PRESETS`，非凭空编造。

**F-1 · 后端 `PRESETS` 两模式逐字相同（致命现状）**
`PRESETS["balanced"]` 与 `PRESETS["aggressive"]` 均为 `[politeness, role_prefix, empty_items, duplicate_lines, blank_lines]`（文件 64–73 行）。`mode` 仅通过 `aggressive_like` 影响两条规则：
- `_rule_politeness`：`aggressive_like=True` 时叠加 `_CN_FILLERS_AGGRESSIVE` / `_EN_FILLERS_AGGRESSIVE` 且删单字「请」；
- `_rule_role_prefix`：`aggressive_like=True` 时追加行内 CN 角色前缀兜底移除。
→ **根因 A**：当走 `rules=None` 路径时，两模式除了 politeness 多删几个词外**别无差异**，用户自然"看不出区别"。

**F-2 · 前端 `SIMPLIFY_PRESETS` 虽不同但差异浅**
`app.js` 548–551：`balanced`(10 类) = 5 基础 + `meta_comment`/`logical_connector`/`filler_particles`/`duplicate_clauses`/`punctuation_compress`；`aggressive`(13 类) = balanced + `hedging`/`redundant_adverbs`/`examples_trim`。差异仅在"多了 3 个同类别"，且这 3 类对短 prompt 常不触发；`mode=aggressive` 在词法上的额外收益也只落在 politeness/role_prefix。
→ **根因 B**：前端预设的差异是"同类堆叠"，不是"类别级 + 深度级"的真实分层，用户感知弱。

**F-3 · 无第一人称自指类别，自指冗余存活**
15 条规则中**没有任何一条**系统性处理第一人称自指。现有 politeness 词典仅覆盖：
- `_CN_FILLERS_BALANCED`：请您 / 我希望 / 我想让你 / 我想要你 / 我需要你 / 你需要 / 你应该…（多为"对模型的指令/客套"，且混了第二人称）；
- `_CN_FILLERS_EXPANDED`（仅 `explicit=True` 叠加）：帮我 / 替我 / 麻烦您 / 拜托…；
- **缺失**：给我 / 和我 / 为我 / 由我 / 同我 / 向我 / 对我 / 依我看 / 在我看来 / 我个人认为 / 我想 / 我打算 / 请帮我 / 麻烦帮我… 完全不在任何词表。
→ **根因 C**：用户举例的"给我 / 和我"在 balanced 与 aggressive **两种模式都存活**（前端 `explicit=True` 也只叠加 expanded 的"帮我/替我"，不含"给我/和我"）。

**F-4 · 护栏资产已具备，可复用**
- 否定护栏 `_NEG_LOOKBEHIND`（181–184 行）已覆盖 不/没/别/未/无/莫/非/勿，1–3 字否定辖域；
- 保护集 `_PROTECT_RE`（138–142 行）已冻结 ```代码块 / 行内代码 / URL；`_PROTECT_WORDS` 已保护"申请/请求/请教"等含「请」安全词。
→ 新规则与深化均**直接复用**，不新增依赖、不重复造轮子。

---

## ④ 核心设计原则（规范化总纲）

- **原则 A · 意图守恒**：任何删除后，任务意图 / 约束 / 否定 / 代码 / 专有名词 / 数字 / 英文 token **不变**。删除只移除非承载信息的冗余。
- **原则 B · 模式分层**：
  - `balanced`（保守）= 去客套与安全冗余（5 基础 + 轻量元评论/语气词/标点/跨句重复），**不做**自指/弱语气/连接词的深度清理；
  - `aggressive`（激进）= 在 balanced 基础上**追加** `first_person`(自指) + `hedging`(弱语气) + `redundant_adverbs`(冗余副词) + `examples_trim`(过长示例) + `logical_connector`(连接词)，且**同类规则内 aggressive 命中集更广**（politeness 走 aggressive 词表 + 单字「请」 + expanded；role_prefix 走行内兜底）。
- **原则 C · 零回归**：`rules=None` 仍 ≡ v2.5（PRESETS 只含 5 基础类）。任何新类别（`first_person` 及更深清理）一律 **explicit-only**，由前端默认勾选 + 显式下发 `rules` 生效，**不进 `PRESETS`**。
- **原则 D · 否定护栏**：被 不/没/别/未/无/莫/非/勿 辖域覆盖的词**绝不删**（沿用 `_NEG_LOOKBEHIND` 思路，必要时扩展到更长否定结构）。
- **原则 E · 保护集**：代码块 / 行内代码 / URL / 专有名词 / 数字 / 英文 token **冻结**（沿用 `_PROTECT_RE` / `_PROTECT_WORDS`），规则内部不得触碰。

---

## ⑤ 模式差异规范（必须具体）

### 5.1 目标差异模型

| 维度 | balanced（保守） | aggressive（激进） |
|---|---|---|
| **类别集合** | 5 基础 + `meta_comment` + `filler_particles` + `duplicate_clauses` + `punctuation_compress` + `punctuation_normalize` | **balanced 全集** + `first_person` + `hedging` + `redundant_adverbs` + `examples_trim` + `logical_connector` |
| **politeness 命中深度** | balanced 词表 + expanded + 单字「请」(前端 explicit 路径) | balanced 词表 + expanded + 单字「请」 + **aggressive 词表**（麻烦/劳烦/辛苦/拜托/尽量/最好/一定/务必… + 英文 you are a / your task is to / just / simply / very…） |
| **role_prefix 命中深度** | 仅行首长前缀精简 | 行首 + **行内 CN 角色前缀兜底移除** |
| **自指冗余** | 保留（不删"给我/和我"） | **删除**（first_person 生效） |
| **弱语气 / 冗余副词 / 连接词 / 过长示例** | 保留 | **删除** |

> 注：上表为**推荐预设**。是否把 `logical_connector` 从 balanced 移到 aggressive-only（使差距更大），见 §⑨ Q2。无论怎样，`aggressive ⊃ balanced` 且"同类更深"两条必须成立，差异才可被用户一眼识别。

### 5.2 同一输入 · 两种模式输出对比（示意，基于规则行为的预期差异）

**输入：**
```
你好，请给我写一个 Python 爬虫，要能爬豆瓣 TOP250，并且把结果存成 CSV。
另外，我希望你能处理好反爬，这个爬虫最好能非常稳定地运行。谢谢！
```

**balanced（保守）输出（预期）：**
```
给我写一个 Python 爬虫，要能爬豆瓣 TOP250，把结果存成 CSV。
你能处理好反爬，这个爬虫最好能非常稳定地运行。
```
> 已删：你好 / 单字「请」(explicit) / 另外(meta_comment) / 并且(logical_connector) / 谢谢。
> **保留**：「给我」（无 first_person）、「最好能」「非常」（hedging/redundant_adverbs 不在 balanced）。

**aggressive（激进）输出（预期）：**
```
写一个 Python 爬虫，要能爬豆瓣 TOP250，把结果存成 CSV。
处理好反爬，这个爬虫能稳定地运行。
```
> 在 balanced 基础上**追加删**：「给我」(first_person) / 「最好」(aggressive 词表) / 「非常」(redundant_adverbs) / 「能…地」弱化。

→ 差异**一眼可见**：保守留"给我 / 最好能非常稳定"，激进清掉自指与弱语气。这正是用户要的"看得出的区别"。

---

## ⑥ 自指冗余新规则 `first_person`（explicit-only）规范

### 6.1 定义
独立成类，专管「说话人自己的冗余自指标记」——把一个默认就是"我向模型提需求"的 prompt 中，显式点明 *我 / 给我 / 和我 / 为我 / 由我 / 依我看* 等冗余主语 / 受益 / 视角标记。删去后任务意图不变（对话语境已隐含"我"）。

### 6.2 应删除的筛选标准（词典草案，长词优先排序）

| 子类 | 词条草案 |
|---|---|
| 受益 / 对象标记 | 给我、为我、替我、帮我、由我、同我、和我、向我、对我、与我 |
| 视角 / 意见标记 | 依我看、在我看来、我个人认为、我个人觉得、以我之见、照我说 |
| 意愿 / 需求标记（第一人称） | 我想要、我希望、我需要、我想、我打算、我计划、我要求、我期待、我建议、我考虑 |
| 客套求助 | 请帮我、麻烦帮我、劳烦帮我、求你帮我、麻烦你帮我 |

> 实现提示（供架构师，非本 PRD 写码）：词条长→短排序后短语级 `replace`；"我想"等须锚定后接动词（想做/想要/我想让/我想看/我想知/我想去/我想写/我想创建/我想生成/我想实现）以避免误删"我想你"；裸字"我"**默认不删**（仅在明确受益/意愿动词构式中才删），降低误删。

### 6.3 应保留（不删）的边界

1. **"我"承载关键区分信息**：「我和张三的日程」「我的账号和你的账号」→ "我/我的"提供必要区分，**保留**；「把我的文件发给张三」中"我的"是必要所属，**保留**。
2. **否定辖域覆盖**：被 不/没/别/未/无/莫/非/勿 辖域覆盖的自指标记，遵循原则 D 不删（细节见 §6.4）。
3. **保护集内**：代码块 / 行内代码 / URL / 专有名词 / 数字 / 英文 token 中的"我/me/my"**冻结**（原则 E）。
4. **句法必要性**："给我看看报错"中"给我看看"为整体祈使，删"给我"→"看看报错"意图可接受；但"给…我…"跨词不连续时不匹配，天然保留。

### 6.4 否定护栏与边界（深化点）

- 复用 `_NEG_LOOKBEHIND`（1–3 字否定辖域）。
- **细化规则**：否定词**之前**的自指标记正常删（"别给我发邮件"→"别发邮件"，意图一致）；否定词**直接辖域内的自指标记**（"不要给我 X"中"给我"是否定对象的一部分）建议**保留**，避免改变"不要给我"的边界语义——具体取舍见 §⑨ Q3。
- 长否定结构（"完全没有可能""并没有完全"）当前 1–3 字护栏可能漏护，需在 `first_person` 与既有 hedging/redundant_adverbs 共用更长的否定前瞻（P1）。

### 6.5 与 `politeness` 的分工

- `politeness`：管"对模型的客套 / 指令语气"（您 / 请 / 谢谢 / 你应该 / 你必须）。
- `first_person`：管"说话人自己的冗余自指标记"（给我 / 和我 / 我想 / 依我看）。
- 两者可同开、互不替代；`first_person` 补齐了 politeness 一直缺失的"给我 / 和我 / 为我"缺口，并使"第一人称自指"这一标准**可枚举、可解释**。

---

## ⑦ 15 条规则规范化筛选标准清单（全部列出）

> 每格：(a) 当前标准简述 → (b) 规范化目标 → (c) balanced/aggressive 差异 → (d) 已知漏洞 / 待补。
> 标注 **[深化]** 表示本增量需重点增强。

### 7.1 总览表

| # | 规则 id | 当前标准(a) | 规范化目标(b) | 模式差异(c) | 已知漏洞 / 待补(d) |
|---|---|---|---|---|---|
| 1 | politeness | 中/英礼貌-冗余短语移除；balanced/aggressive 两档词表 + explicit 叠加 expanded；aggressive_like/explicit 时删单字「请」 | 客套/指令语气统一归属，与 first_person 清晰分工 | aggressive 追加 `_CN/_EN_FILLERS_AGGRESSIVE`（麻烦/劳烦/辛苦/拜托/尽量/最好/一定/务必… + 英文 you are a/your task is to/just/simply/very…） | ① 缺系统自指（给我/和我）→ 由 first_person 补；② "请帮我"删「请」后"帮我"靠 expanded；③ 中英混排"please 给我"英文删、中文留（待 first_person） |
| 2 | role_prefix | 行首冗长角色前缀→"角色："；aggressive 行内 CN 兜底 | 角色前缀归一化标准明确（行首/行内可配） | aggressive 追加行内 CN 角色前缀删除 | ① 行内兜底可能误删正文"你是一个函数"；② 英文行内角色未处理；③ 与 first_person 重叠（"我希望你扮演"→角色：，但"我希望"残留需 first_person） |
| 3 | empty_items | 删行首 `- * • +` / 数字.)/) / 字母.)/) 之后空内容的列表项 | 明确"空"定义（仅空白） | 无 | ① 仅单行 bullet 正则，缩进/嵌套有限；② 中文顿号列表不识别；③ 与 examples_trim 边界 |
| 4 | duplicate_lines | 按归一化（去空白/标点/小写）合并重复行 | 明确归一化规则 + 跨大小写/全半角 | 无 | ① 仅整行级，行内重复由 duplicate_clauses 补；② 去标点可能误并仅标点不同的两行（低风险）；③ 不处理"近似"重复 |
| 5 | blank_lines | 折叠连续空行≤1 + 行首尾空白清理 | 明确"连续空行"定义 | 无 | ① 首尾空行清理可能改刻意排版（代码块前后）；② 与 `_restore` 后二次折叠可能 double |
| 6 | meta_comment | 短语级删元评论/过渡句（`_META_COMMENT`） | 明确"元评论"边界（不删承载信息的过渡） | 无（同表） | ① "此外/另外/还有/同时"在并列增补常承载语义；② "需要注意的是/值得注意的是"可能引出关键约束，误删风险；③ 与 logical_connector 重叠词已去重但计数归属需明确 **[深化]** |
| 7 | hedging | 删弱语气/不确定词（`_HEDGING`+追加多字），带否定前瞻 | 明确弱语气边界 + 否定护栏覆盖 | 无（同表） | **① 「应该」被追加入 hedging（P1）却在指令中常表强约束（"你应该返回 JSON"）→ 误删风险高！** ② 长否定结构（"完全没有可能"）1–3 字护栏可能漏护 **[深化]** |
| 8 | redundant_adverbs | 删冗余副词/强调（`_REDUNDANT_ADV`：非常/十分/极其/完全…），带否定前瞻 | 明确"冗余"判定（强调性 vs 区分性副词） | 无（同表） | ① "完全"在"完全不同的方案"是区分性，删后语义弱化；② 与 hedging 重叠（完全/绝对） **[深化]** |
| 9 | examples_trim | 示例引导词后连续块≥4 行或≥200 字符→压缩为前 3 行+标注，带保护 token 无损 | 明确"示例块"边界 + 阈值可配 | 无（同表） | ① 阈值固定不可配；② "例如"在正文非示例时误触发；③ 仅压缩不删除，前 3 行仍可能冗余；④ 与 semantic_compress 顺序未定义 |
| 10 | logical_connector | 删逻辑/序列/总结/过渡连接词（`_LOGICAL_CONNECTORS`，去重 `_META_COMMENT`），否定前瞻 + 有序列表行内序列词保护（局部哨兵） | 明确连接词分类 + 序列词保护边界 | 无（同表） | ① "并且/同时/以及"并列中常必要；② 条件标记 `_CONDITIONAL_MARKERS` 硬排除 OK；③ "其实/事实上/实际上"解释时有必要；④ 局部哨兵仅护有序列表行，无序列表（`- *`）行内序列词（首先/然后）仍被删 **[深化]** |
| 11 | filler_particles | 删句末语气助词（啊/呢/吧…），仅句末（后接。！？.!?…或文末），否定前瞻，「吗」刻意排除 | 明确"句末"判定 | 无（同表） | ① 仅句末，句中语气词（"这个呢，那个"）不删（保守 OK）；② 单字集合可能误删专有名词尾字（罕见）；③ 否定前瞻防"不啊"OK |
| 12 | duplicate_clauses | 跨句完全重复子句去重（整句精确重复 / 长重复前缀），explicit-only，阈值 `_DUP_CLAUSE_MIN_LEN=4` CJK | 明确"子句"切分 + 阈值护栏 | 无（同表） | ① 仅整句级（以。！？切），不处理跨标点长句；② 阈值 4 可能放过小重复（3 字）；③ 与 duplicate_lines 分工（行 vs 句）；④ 不处理语义重复（由 semantic_compress 补） |
| 13 | punctuation_compress | 3+ 连续 。！？.!? → 单字符，explicit-only，排除 ASCII `.` 保护 `...` | 明确折叠集 | 无（同表） | ① 仅 3+，2 个连续由 punctuation_normalize 补；② ASCII `?`/`!` 连续折叠；③ 与 punctuation_normalize 重叠 |
| 14 | punctuation_normalize | 2+ 连续相同 CJK 标点（，。！？；：、）折叠 + 标点周围 ASCII 空格规整，explicit-only | 明确归一化范围（仅冗余，不删有义标点） | 无（同表） | ① `，`连续折叠可能误并；② 空格规整可能误删中英文间必要空格（"Python 爬虫"→"Python爬虫"）；③ 与 punctuation_compress 顺序无冲突 |
| 15 | semantic_compress | 本地 embedding 近义/重复句折叠（能力1）+ 可选重要性剪枝（能力2, prune），explicit-only，embedding 不可用静默跳过 | 明确阈值 + 保护提示 + 可复现 | 无（不进预设） | ① 依赖本地 embedding，无则完全跳过（用户"开了没反应"）；② 阈值 0.90 可能误并语义相近但不同的句；③ 剪枝（prune）误删低信息但必要句；④ `_SEMANTIC_PROTECT_HINTS` 含"不/没/无/勿/别"单字→含否定即保护（合理但偏过保护） |

### 7.2 重点深化规则详述

**politeness [深化]**：明确"客套/指令语气"边界，把第一人称自指整体移交 `first_person`；aggressive 词表维持"麻烦/劳烦/辛苦/拜托/尽量/最好/一定/务必"等，但**删除「最好」在 balanced 的残留**（当前 balanced 不含"最好"，OK）。新增"请帮我/麻烦帮我"类移交 first_person 的客套求助子类，避免与 politeness 重复计数。

**hedging [深化 · 高优先修复]**：`_HEDGING` 在 P1 追加入"应该"，但"应该"在指令语境（"你应该返回 JSON""模型应该先验证输入"）是**强约束**而非弱语气，**误删风险高**。建议：把"应该"从 hedging 移除，或仅在"我认为应该/大概应该"等弱语气构式中才删；并强化否定护栏覆盖长否定结构。

**redundant_adverbs [深化]**：区分"强调性冗余"（"非常感谢"→"感谢"）与"区分性副词"（"完全不同的方案"中"完全"承载区分）。建议对区分性用法加轻量保护（后接"不同/相反/独立/新的"等对比词时不删），或仅在 aggressive 模式删"完全/绝对"。

**logical_connector [深化]**：当前局部哨兵仅保护**有序列表行**（`_ORDERED_LIST_LINE_RE`）内的序列词；无序列表（`- * • +` 引导）中的"首先/然后/最后"作为步骤提示常被误删。建议把无序列表行也纳入序列词保护，或仅删纯连接性词（因此/但是/总之）而保留序列步骤词。

**meta_comment [深化]**：`"需要注意的是/值得注意的是/明确地说"` 可能引出关键约束，纯短语删除有风险。建议：仅在句首且后接逗号/句号（纯过渡）时删，若后接关键内容（"需要注意的是**必须**先…"）则保留；与 logical_connector 的重叠词统一计数归属。

**examples_trim [深化]**：阈值（4 行 / 200 字符）固化，建议提升为可配参数（与 semantic 阈值同思路）；并明确与 semantic_compress 的执行顺序（先 examples_trim 再 semantic_compress，避免示例块内重复句被语义层误并）。

---

## ⑧ 需求池（P0 / P1 / P2）

### P0 — 必须（模式差异 + first_person + 现有规则深化）

| 编号 | 需求 | 验收标准 |
|---|---|---|
| P0-1 | **模式差异实体化**（前端 `SIMPLIFY_PRESETS` 真正分层） | ① `aggressive` 严格 ⊃ `balanced`；② aggressive 额外含 `first_person` + `hedging` + `redundant_adverbs` + `examples_trim` + `logical_connector`，且同类规则 aggressive 命中集更广；③ 同段输入两模式输出肉眼可辨差异（见 §5.2）。**后端 `PRESETS` 不动**（零回归红线）。 |
| P0-2 | 新增 `first_person` 规则类（explicit-only） | ① 新增 `_rule_first_person(work, aggressive_like, explicit)` 并注册 `RULE_REGISTRY` / `ALL_RULE_IDS`(15→16) / `CANONICAL_ORDER`（建议置于 `politeness` 之后）；② `default_in_presets: False`，**不进后端 `PRESETS`**；③ 复用 `_protect`/`_restore` + `_NEG_LOOKBEHIND`；④ 删除"给我/和我/为我/由我/依我看/我想/我希望/请帮我"等（§6.2），保留"我的/我和 X"等必要区分（§6.3）。 |
| P0-3 | **现有规则深化**（hedging 修复 + 边界强化） | ① 移除/约束 hedging 中的"应该"误删（强约束保护）；② redundant_adverbs 对区分性用法加保护；③ meta_comment 仅纯过渡时删；④ 上述均不破坏 `rules=None` 契约。 |
| P0-4 | 全部规则筛选标准**前端可枚举展示** | 前端「简化」页新增"规则说明"面板，逐条展示 16 类规则的筛选标准 / 命中示例 / 保留边界（数据来源 `ALL_RULE_IDS` + 一份规则元数据表），满足用户"全部列出来"。 |

### P1 — 重要（更细护栏 / 体验）

| 编号 | 需求 | 验收标准 |
|---|---|---|
| P1-1 | 更长的否定护栏 | hedging / redundant_adverbs / first_person 共用扩展否定前瞻（覆盖 >3 字长否定结构，如"完全没有可能"），避免漏护。 |
| P1-2 | logical_connector 无序列表序列词保护 | 无序列表（`- * • +`）行内"首先/然后/最后"等步骤提示纳入保护，避免误删。 |
| P1-3 | examples_trim 阈值可配 | 示例块折叠阈值（行数 / 字符数）提升为可配参数，默认沿用当前值。 |
| P1-4 | 规则命中计数去重归属 | meta_comment 与 logical_connector 重叠词统一计数归属，避免同词在两类被重复计费。 |

### P2 — 锦上添花

| 编号 | 需求 | 验收标准 |
|---|---|---|
| P2-1 | 英文第一人称冗余 | 补齐英文自指（"for me / to me / I want / I would like / please help me"）到 first_person，与中文同构。 |
| P2-2 | 自定义预设保存 | 用户勾选组合可"保存为我的预设"（localStorage），恢复时高亮"自定义"。 |
| P2-3 | 模式差异可视化对比 | 结果区并排展示 balanced vs aggressive 输出 diff，强化"看得出的区别"。 |

---

## ⑨ 待确认问题

1. **Q1 · `first_person` 是否仅进 aggressive 预设？**
   本 PRD 设计为 aggressive 追加、balanced 保留自指（保守）。但用户原话"给我/和我 为什么还存在"暗示其希望**默认就清掉**。是否也让 balanced 默认含 `first_person`（轻度）？倾向：aggressive 必含、balanced 默认不含（保守语义），但可由主理人/用户拍板。

2. **Q2 · `logical_connector` 是否从 balanced 移到 aggressive-only？**
   当前前端 balanced 已含 `logical_connector`。若移到 aggressive-only，两模式差距更大、更"一眼可辨"；但会改变当前 balanced 用户的习惯（少删连接词）。请定夺。

3. **Q3 · 否定辖域内的自指标记（"不要给我 X"）删不删？**
   否定词**之前**的自指标记（"别给我发邮件"→"别发邮件"）建议删；否定词**直接辖域内**的（"不要给我 X"）建议保留以保边界。此细化是否采纳？

4. **Q4 · 删"给我"后，"请给我 X"→"请 X"还是"X"？**
   politeness 与 first_person 执行顺序：若 first_person 先于 politeness，则"请给我 X"→ first_person 删"给我"→"请 X"→ politeness(aggressive) 删"请"→"X"；若反之则"请 X"→"X"。建议 first_person 紧接 politeness 之后（CANONICAL_ORDER 中 politeness 后），最终 aggressive 输出"X"，符合深度清理。请确认语义预期。

5. **Q5 · aggressive 是否默认开启 `semantic_compress`？**
   沿用 v2.9 决策：`semantic_compress` 保持 explicit-only、不进任何预设、默认不勾选（需本地 embedding）。本次不改动；如要进 aggressive 预设须同步改前端且仅 explicit 路径。

---

## ⑩ 硬约束（红线，务必遵守）

- **C-1 零新增 pip 运行时依赖**：仅 Python 标准库 + 现有 `tokenizer` / `scorer`；`first_person` 与深化全部复用 `_protect` / `_restore` / `_NEG_LOOKBEHIND` / `_PROTECT_RE`。
- **C-2 不改 `rules=None` 零回归契约**：后端 `PRESETS` 只允许含那 5 个基础类；任何新类别（`first_person` 及更深清理）一律 explicit-only，由前端默认勾选 + 显式下发 `rules` 生效，**不进 `PRESETS`**。
- **C-3 提交规范**：Hyhyhyyy-only 提交，**无 Co-Authored-By**。
- **C-4 不触碰 `nul` / `run.bat`**：保持原样，禁止修改。

---

## ⑪ 落地改动清单（供架构师速览）

- `prompt_simplifier.py`：
  - 新增 `_FIRST_PERSON_*`（受益/视角/意愿/客套求助 四类词表，长词优先）+ 复用 `_NEG_LOOKBEHIND`；
  - 新增 `_rule_first_person(work, aggressive_like, explicit)`；
  - `ALL_RULE_IDS` 15→**16**、`CANONICAL_ORDER` 在 `politeness` 后追加 `first_person`、`RULE_REGISTRY` +1（`default_in_presets: False`）；
  - `simplify_prompt` 主循环在 politeness 之后插入 `first_person` 分支（均 `_tag(..., explicit)`）；
  - **深化**：hedging 移除/约束"应该"、redundant_adverbs 区分性保护、meta_comment 纯过渡才删、logical_connector 无序列表序列词保护（P1）；
  - `PRESETS`（5 基础类）**不动**。
- `server.py`：`/api/simplify` 已透传 `rules`，无需改契约；`first_person` 经 `rules` 显式下发即生效。
- `frontend/app.js`：
  - `SIMPLIFY_RULE_IDS` 15→16；
  - `SIMPLIFY_PRESETS` 按 §5.1 重分层（aggressive 追加 `first_person`+`hedging`+`redundant_adverbs`+`examples_trim`+`logical_connector`）；
  - 新增"规则说明"面板（16 类规则元数据：筛选标准 / 命中示例 / 保留边界）满足"全部列出来"；
  - `localStorage` key 升 `v2_11`（迁移 `v2_9`）。
- `frontend/index.html`：`进阶精简` 分组新增 `data-rule="first_person"` 复选框；新增"规则说明"展开区。
- 测试（QA 后续写）：`test_first_person_removes_geiwo` / `test_first_person_keeps_wode` / `test_mode_difference_perceptible` / `test_hedging_no_delete_yinggai_constraint` / `test_rules_none_zero_regression`（PRESETS 仍 5 类、输出逐字 v2.5）/ `test_all_rule_ids_exact`（15→16）。
