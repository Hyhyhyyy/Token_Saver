# PRD · SkillForge 通用 Prompt 简化器（增量 evo2-6）

> 版本线：2.5.0-evo → 2.6.0-evo（版本号由主理人处理 `__init__`，本增量仅出分析与文档，不改源码）。
> 约束：零新增 pip 运行时依赖（仅 stdlib + fastapi/uvicorn/pyyaml/tiktoken）；前端零构建（原生 HTML/CSS/JS）；接口向后兼容。
> 范围**仅**限「通用 Prompt 简化器」：`prompt_simplifier.py` / `/api/simplify` / 前端简化视图。**不**动 SKILL.md 清洗（`cleaner.py` / `/api/clean` / `/api/apply`）。
> 本 PRD 基于逐文件深读现状（`prompt_simplifier.py` 全文、`server.py` 216–234、`app.js` 535–609、`index.html` 85–114）产出。

---

## 1. 项目信息

- **Language**：中文
- **Programming Language**：Python（stdlib + 现有依赖）+ 原生 HTML/CSS/JS（前端零构建，不引入框架/图表库）
- **Project Name**：`skill_forge`
- **目标版本**：`2.6.0-evo`（建议；具体由主理人定）
- **原始需求复述**：
  - 现状"简化效果不好"——`simplify_prompt()` 仅删礼貌词、行首角色前缀、空列表项、逐字重复行，漏掉大量真实冗余（元评论/过渡句、弱语气词、冗余副词、过长示例等）。
  - 诉求①：**进一步强化简化规则**，覆盖更多真实冗余。
  - 诉求②：把"简化哪些内容"做成**可配置、分类、可多选**的规则，供用户按需勾选。给出 9 个候选类别（见 §3 分类目录）。
  - 诉求③：前端把 `balanced`/`aggressive` 二选一 radio，升级为「**分组勾选 + 保守/激进两个预设按钮**」。

---

## 2. 产品目标

- **G1（简化更强）**：在保持语义/结构无损的前提下，显著提升真实冗余的覆盖率（新增 meta_comment / hedging / redundant_adverbs / examples_trim 四类规则）。
- **G2（可控可配）**：把简化维度拆成可独立开关的分类规则，用户既能手动勾选，也能一键套用预设，贴合不同场景（代码 prompt vs 文案 prompt）。
- **G3（零回归 + 兼容）**：新增配置能力的同时，不破坏既有保护机制（代码块/行内代码/URL 冻结）、不破坏 `/api/simplify` 既有调用方、不改变"rules 缺省"时的输出行为。

正交、不堆砌：P0 只放会**破坏既有行为/需仔细设计**的项；P1 放新规则类别与 UI；P2 放锦上添花。

---

## 3. 分类目录（规则类别 ↔ 现状资产 ↔ 触发示例）

| 类别 id | 名称 | 现状资产对应 | 触发示例 | 默认开（保守 / 激进）¹ |
|---|---|---|---|---|
| `politeness` | 礼貌/客气填充词 | `_CN_FILLERS_*` + `_EN_FILLERS_*`（balanced 与 aggressive 两档） | "您好，请你帮我…" / "Please make sure to…" / "谢谢" | 开 / 开 |
| `role_prefix` | 冗长角色前缀精简 | `_ROLE_PREFIXES`（行首）+ `_ROLE_PREFIX_CN`（aggressive 行内兜底） | "你是一个专业的 Python 工程师，擅长…" → "角色：Python 工程师，擅长…" | 开 / 开 |
| `empty_items` | 空列表项/空编号 | `_EMPTY_BULLET_RE` | 行首 `- ` / `1. ` / `a) `（无后续内容） | 开 / 开 |
| `duplicate_lines` | 重复/近 identical 指令合并 | `_norm_line` 去重 | "请检查代码" 与 "请 检查 代码。"（归一化后相同） | 开 / 开 |
| `meta_comment` | 元评论/过渡句（**新增**） | 新增词典 | "需要注意的是…" / "换句话说…" / "让我来帮你" / "此外" / "另外" | 开 / 开 ² |
| `hedging` | 弱语气/不确定性词（**新增**） | 新增词典（含原 aggressive 的 尽量/尽可能） | "你可能需要先安装依赖" / "一般来说，这种情况…" | 关 / 开 ² |
| `redundant_adverbs` | 冗余副词/强调（**新增**） | 新增词典（含原 balanced 的 非常/十分、aggressive 的 务必/一定） | "请你务必仔细检查" / "这是一个非常关键的步骤" | 关 / 开 ² |
| `examples_trim` | 过长示例压缩/截断（**新增，激进**） | 新增逻辑（示例块识别 + 截断/压缩） | "例如：\n- 案例1\n…(20 行)" → 截断为前 N 行 + 标注 | 关 / 关 ² |
| `blank_lines` | 空行折叠 | `_collapse_blank_lines`（当前始终执行） | 连续空行折叠为至多 1 个 | 开 / 开 |

> ¹ 默认开关指"预设"对应的规则集合，详见 P1-7。² `meta_comment`/`hedging`/`redundant_adverbs`/`examples_trim` 的预设归属为**待确认问题 Q1/Q2**。

---

## 4. 用户故事

- US-1（作为提示词作者）：我希望简化器不仅能删"你好/请"，还能干掉"需要注意的是/总的来说/换句话说"这类元评论与"可能/也许"这类弱语气词，让压缩更彻底。
- US-2（作为开发者）：我希望把含大段示例的 prompt 丢进去时，过长示例能被压缩/截断，但代码块、行内代码、URL 永远不动。
- US-3（作为进阶用户）：我希望按需勾选规则——比如写代码 prompt 时关掉 `meta_comment`、开 `examples_trim`；写文案 prompt 时全开——而不是只有"均衡/激进"两档。
- US-4（作为普通用户）：我希望一键点"保守"或"激进"预设即可，不必逐项理解每个分类。
- US-5（作为既有调用方/API 用户）：我希望 `/api/simplify` 老调用（只传 `{text, mode}`）行为不变，新规则是可选增量。

---

## 5. 需求池

### 5.1 P0 — 必须（破坏既有行为 / 需仔细设计）

#### P0-1 `/api/simplify` 向后兼容 + 新增可选 `rules`
- **对应类别**：全部（接口层）。
- **现状**：`server.py:218-234` 读 `{text, mode?}`（mode 默认 `balanced`），调用 `simplify_prompt(text, mode=mode)`。
- **增量**：请求体新增可选 `rules: list[str]`（元素为 §3 的类别 id）。`simplify_prompt` 新增可选参数 `rules: list[str] | None = None`。
- **映射**：`rules` 缺省 → 沿用现有 `mode` 行为（balanced/aggressive 作为预设映射，见 P1-7）；`rules` 传入 → 以传入集合为准，`mode` 退化为仅"预设提示"语义（不强制）。
- **验收**：
  1. 仅传 `{text}` 或 `{text, mode}` 时，返回结构与现版**完全一致**（含 `changes` 文案格式）。
  2. 传入非法 id（不在 §3 集合）时**忽略**该 id 不 500；空数组 `[]` 表示"只做保护 + 空行折叠（blank_lines），不删任何内容"。
  3. `simplify_prompt` 旧签名 `simplify_prompt(text, mode)` 仍可调用（位置/默认参数不变）。

#### P0-2 保护机制不可破坏（代码块 / 行内代码 / URL 冻结）
- **对应类别**：全部（尤其 `examples_trim`、`meta_comment` 新增逻辑）。
- **现状**：`_PROTECT_RE` + `_protect`/`_restore` 已冻结 `````` ```...``` ````、`` `...` ``、URL；`_PROTECT_WORDS` 保护含"请"的合法词。
- **增量**：所有新增规则类别**必须**在 `_protect` 之后、`_restore` 之前作用于已脱敏文本；新增词典不得匹配到占位符内部。
- **验收**：
  1. 对含 fenced code block / 行内代码 / URL 的样例，简化后这些片段**逐字节不变**（新增规则不得误删/误改）。
  2. 含"申请/请求/请教"等 `_PROTECT_WORDS` 的句子，单字"请"不被误删。
  3. 新增回归用例 `test_simplify_protect_new_rules`：覆盖 examples_trim 截断边界恰好落在代码块附近的场景。

#### P0-3 默认行为零回归（rules 缺省 ≡ 现版）
- **对应类别**：`politeness`/`role_prefix`/`empty_items`/`duplicate_lines`/`blank_lines`。
- **增量**：把现状"两档硬编码"重构成"预设 = 类别集合"后，`balanced`/`aggressive` 预设必须产出与现版**逐字相同**的 `simplified_text`（对既有样例）。
- **验收**：选取 ≥10 条现存测试/示例 prompt，断言重构后 `balanced`、`aggressive` 输出与重构前**字符串相等**（`tokens_saved` 等统计一致）。
- **测试建议**：新增 `tests/test_simplify_parity.py`，fixture 复用仓库内既有 prompt 样例。

#### P0-4 既有填充词资产按分类重组、不丢覆盖
- **对应类别**：`politeness`/`role_prefix`/`redundant_adverbs`（含原 balanced 的 非常/十分、aggressive 的 务必/一定/尽量/尽可能/单字"请"）。
- **增量**：原 `_CN_FILLERS_*`/`_EN_FILLERS_*` 与"单字请移除""行内角色前缀兜底"必须**完整并入**对应类别，不得因重构而漏删。
- **验收**：重构后对任意含原 aggressive 专属词的样例（如"请你务必""你是一个专业的"行内出现），删除条数 **≥** 现版（不回退）。
- **待确认**：原 aggressive 专属的"行内角色前缀兜底移除"与"单字请移除"归入 `role_prefix` / `politeness` 还是保留为 aggressive-only 行为——见 Q3。

### 5.2 P1 — 重要（新规则类别 + UI）

#### P1-1 新增 `meta_comment` 规则类别
- **触发示例**："需要注意的是，…" / "总的来说，…" / "简单来说，…" / "换句话说，…" / "我会帮你…" / "让我来…" / "当然，…" / "此外/另外，…" / "综上所述/总而言之/简而言之/说白了"。
- **验收**：整词/短语级移除（行内安全移除，不破坏句子主干）；对含代码块/URL 的样例不误伤（复用 P0-2 保护）。

#### P1-2 新增 `hedging` 规则类别
- **触发示例**："可能/也许/大概/或许/似乎/恐怕" / "尽量/尽可能" / "某种程度上/一般来说/不妨"。
- **验收**：仅移除弱语气词本身，不删其修饰的核心指令（如"你可能需要安装"→"你需要安装"）；与 `politeness` 的"尽量"去重，不重复计数。

#### P1-3 新增 `redundant_adverbs` 规则类别
- **触发示例**："非常/十分/极其/彻底/完全/一定/务必/绝对/特别/相当" 作冗余强调时。
- **验收**：移除副词但保留被修饰语义（"非常关键"→"关键"）；与既有 balanced（非常/十分）、aggressive（务必/一定）去重合并，覆盖不降。

#### P1-4 新增 `examples_trim` 规则类别（含截断策略）
- **触发**：识别示例块——行首/句中 "例如/例如：/比如/举个例/e.g./for example/for instance" 之后跟随的多行列表或长段落，超阈值（如 ≥ N 行或 ≥ M 字符）则压缩。
- **行为**：保留前 K 行（默认 3）+ 追加标注"（示例已压缩，共 X 行）"；或折叠为单行摘要。必须在 `_protect` 之后执行，代码块不被当示例截断。
- **验收**：超长示例被压缩且标注；非示例长段落不被误截；代码块内的"例如"注释不受影响。截断阈值/标注文案作为 Q2 确认项。

#### P1-5 既有 4 类显性化为可独立开关 + `blank_lines` 显性化
- **对应类别**：`politeness`/`role_prefix`/`empty_items`/`duplicate_lines`/`blank_lines`。
- **增量**：这 5 类从"硬编码流程"改为"受 `rules` 集合控制的可开关步骤"；`blank_lines`（空行折叠）也纳入 `rules`，但预设中默认开启。
- **验收**：`rules=["blank_lines"]` 时只折叠空行、不删任何词；任一类别单独关闭时对应处理被跳过（用 fixture 验证）。

#### P1-6 前端：分组勾选 + 保守/激进预设，替换 radio
- **现状**：`index.html:92-93` 两个 radio（`simplifyMode`：balanced/aggressive）；`app.js:574` 读 `input[name="simplifyMode"]:checked`。
- **增量**：删除 radio，改为 9 个分类 checkbox（分组排列，含中文标签与英文 id 提示）+ 两个预设按钮「保守」「激进」。`doSimplify` 收集勾选项组成 `rules` 数组下发；保留复制/导出按钮与变更日志渲染。
- **验收**：
  1. 默认进入页面按"保守"预设勾选（与现 balanced 体验一致）。
  2. 点「激进」一键套用 aggressive 预设勾选；手动改勾选后，预设按钮呈"自定义"态（视觉即可）。
  3. 请求体为 `{text, rules:[...]}`；不破坏既有 `mode` 兼容（后端 P0-1 兜底）。

#### P1-7 预设 ↔ `rules` 映射定义
- **保守（balanced）预设** = `{politeness, role_prefix, empty_items, duplicate_lines, blank_lines}` ∪ `meta_comment`（见 Q1）。
- **激进（aggressive）预设** = 保守 ∪ `{hedging, redundant_adverbs}` ∪ （`examples_trim` 见 Q2）∪ 原 aggressive 专属（行内角色前缀兜底、单字"请"）。
- **验收**：两套预设的 `rules` 集合可静态枚举、写入文档；前端预设按钮与后端 `mode` 映射一一对应，保证"只点预设"产出与现版一致（接 P0-3）。

### 5.3 P2 — 锦上添花

#### P2-1 记忆上次勾选 / 预设（localStorage）
- 记住上次 `rules` 选择与预设，下次进入自动恢复；可选"保存为我的预设"自定义命名。纯前端，不新增接口。

#### P2-2 变更日志按类别标注
- `changes` 条目细化到类别，如 `"移除 3 处礼貌填充词 [politeness]"`、`"压缩 1 处示例 [examples_trim]"`，提升可解释性。需 `simplify_prompt` 在去重/计数时记录类别来源（向后兼容：旧调用仍返回字符串列表）。

#### P2-3 各类别 token 节省拆解
- 结果区除总节省外，展示每类贡献的 token 数（小条形/列表），帮助用户判断哪类最值。可选，依赖 P2-2 的类别溯源。

---

## 6. UI 线框（新「简化」页 · 仅变更部分）

```
┌─ Prompt 简化器 · 一键压缩你的提示词 ────────────────────────┐
│ <textarea 粘贴/拖拽 .txt>                                    │
│                                                              │
│ 简化规则（可多选）：                                          │
│  [☑] 礼貌填充词 politeness      [☑] 角色前缀 role_prefix      │
│  [☑] 空列表项 empty_items       [☑] 重复指令 duplicate_lines  │
│  [☑] 元评论 meta_comment        [☐] 弱语气 hedging           │
│  [☐] 冗余副词 redundant_adverbs [☐] 示例压缩 examples_trim   │
│  [☑] 空行折叠 blank_lines                                 │
│                                                              │
│  预设：[ 保守 ]  [ 激进 ]   （当前：保守 / 自定义）            │
│  [ ⚡ 一键简化 ]   <err>                                      │
└──────────────────────────────────────────────────────────────┘
        ↓ 结果区（沿用现 card：结果 textarea + 4 项统计 + 复制/导出 + 变更日志）
```

- 分组勾选区：9 个 checkbox，label 含中文名 + 英文 id（小字）；`meta_comment`/`hedging`/`redundant_adverbs`/`examples_trim` 默认按 Q1/Q2 勾选。
- 「保守」「激进」按钮：一键套用 P1-7 预设；用户手改任一 checkbox 后，预设态变"自定义"（按钮不高亮或显示"自定义"）。
- 请求：`POST /api/simplify` 体 `{text, rules:[...]}`；无勾选时 `rules:[]`（只保护+空行折叠）。

---

## 7. 待确认问题（≤3）

1. **Q1 预设 ↔ rules 映射**：`meta_comment` 是否进"保守"预设？`hedging`/`redundant_adverbs` 仅进"激进"还是也进保守？直接决定两套预设的类别集合与默认勾选态。
2. **Q2 `examples_trim` 截断策略与默认开关**：示例如何界定（"例如/e.g." 之后 N 行？还是所有超长行块？）、截断阈值（行数/字符数）、是否加"（示例已压缩）"标注、默认是否**关闭**（即便激进）？该类别最激进、风险最高，需明确边界。
3. **Q3 原 aggressive 专属处理归属**：行内角色前缀兜底移除、单字"请"移除，是并入 `role_prefix`/`politeness` 分类（使其可被独立关闭），还是保留为 aggressive-only 行为（不受 rules 单独控制）？影响 P0-4 重组方式与分类纯净度。
