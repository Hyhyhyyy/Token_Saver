# SkillForge v2.13 增量 PRD —— 诚实不确定性护栏 + 语义剪枝「保留 useful substance」

- **版本**：`2.13.0-evo`（自 `2.12.0-evo` 演进）
- **日期**：2026-08-10 / 11
- **定位**：源于与 steipete/AGENTS.MD 的对比结论——压缩应以「保留有用的实质（useful substance）」为前提，而非盲目求短。
- **提交身份**：Hyhyhyyy（author/committer 均为本人，无 Co-Authored-By / agent / CNB 标记）
- **零新增依赖 / 零构建前端 / 零回归（rules=None ≡ v2.5）** 三硬约束保持不变。

## 0. 背景与动机

v2.11/v2.12 持续深化「规则检测效果」，但出现两类「过度压缩」风险：

1. **hedging 语义翻转**：认知不确定性词（可能/也许/搞不好…）后接负面结果词（不可行/失败/问题…）时，
   删除 hedge 会把「或然」误当「必然」——「可能不可行」→「不可行」，含义被反向坐实。
2. **语义剪枝误删背景信息**：ability2 仅按「离题（与主题质心相似度 < 地板）」剪枝，会把离题但含实质
   （数字、专名、指令）的背景句一并删掉，损失有用信息。

AGENTS.MD 明确指出 *"Prefer useful substance over artificial brevity"*，本迭代将其落成硬规则。

## 1. 硬约束（不可违反）

- `rules=None` 路径字节级等同于 v2.5：两处增强均为 **explicit-only**，仅当用户显式勾选
  `hedging` / `semantic_compress(prune)` 时生效；`PRESETS` 维持 5 个基础类不变。
- 5 个基础规则词表（politeness/role_prefix/empty_items/duplicate_lines/blank_lines）冻结，不触碰。
- 不新增 pip 运行时依赖；不引入新前端构建产物；不触碰 `nul` / `run.bat`。

## 2. 变更清单

### 2.1 hedging —— 诚实不确定性前向护栏（prompt_simplifier.py）
- 新增常量：
  - `_HEDGING_EPISTEMIC`：认知不确定性类 hedge 集合
    `{可能,也许,或许,大概,恐怕,估计,搞不好,说不定,保不齐,八成,十有八九,兴许,多半,约略,大抵}`。
  - `_HEDGING_NEG_RESULT`：负面结果多字词表（不可行/失败/问题/风险/出错/不成立/不符合… 共 50+ 项），
    **刻意不含裸「不/没」**，避免误保。
  - `_HEDGING_NEG_LINK`：hedge 与负面词之间可间隔的 1~2 个弱连接小品词
    `{会,要,而,就,则,将,是,得,也,可,能,必,有,出,生,致,引,导,让,使,令,把}`。
- 新增 `_is_honest_uncertainty(work, end)`：hedge 后（可间隔 1~2 个 link 词）紧跟负面结果词 → 返回 True。
- 改写 `_rule_hedging`：仅对 `_HEDGING_EPISTEMIC` 中的 hedge 应用护栏；命中时**保留**，其余照常删除。
  删除改用「收集匹配 span → 逆序删除」以避免位置错位。
- 边界示例：
  - `可能不可行` → 保留（直接后接）✅
  - `搞不好会失败` / `也许会有问题` → 保留（间隔 link 词）✅
  - `或许不完全成立` → 删除 或许（负面词被「完全」隔断且非直接/link 后接）✅
  - `未免太复杂` / `大抵可行` → 删除（非 epistemic 类，照常召回）✅

### 2.2 semantic_compress ability2 —— 重要性门控（prompt_simplifier.py）
- 新增常量：
  - `_SEMANTIC_IMPORTANCE_HINTS`：指令/专名提示词（请/必须/执行/调用/配置/参数/数据/模型… 共 50+ 项）。
  - `_SEMANTIC_IMPORTANCE_FLOOR = 0.35`。
- 新增 `_score_sentence_importance(sentence) -> [0,1]`：综合 ①指令/专名命中 ②数字出现 ③有效长度 三项打分。
- 改写 ability2 剪枝条件：`max_sim < _SEMANTIC_PRUNE_FLOOR` **且**
  `_score_sentence_importance(sentence) < _SEMANTIC_IMPORTANCE_FLOOR` 才折叠。
  离题但含实质（高重要性）的句保留，防误删 useful substance。
- 与既有 `_SEMANTIC_PROTECT_HINTS` 协同：含指令/代码/否定标记的句永不动；本次新增的「重要性」
  门控额外兜底「离题但信息量大」的句（如「实验在 4 张 A100 上跑了 12 小时才收敛」）。

### 2.3 版本号
- `skillforge/__init__.py`：`__version__` → `2.13.0-evo`。

## 3. 测试（tests/test_simplify_rules.py）

- 更新 `test_hedging_recall_expanded`：移除对「搞不好会失败」的删除断言（该组合现被护栏保护），
  仅断言非负面后接的 未免/大抵 仍删。
- 新增 `test_hedging_keeps_honest_uncertainty`：覆盖「直接后接 / 间隔 link 词 / 非负面仍删」三类。
- 新增 `test_score_sentence_importance`：含指令+数字 → ≥0.35；纯客套/闲聊 → <0.35；空句 → 0.0。
- 新增 `test_semantic_compress_prune_keeps_substantive_offtopic`：离题但含数字+专名的背景句被保留，近义折叠仍发生。
- 全量回归：**188 passed**（v2.12 为 185，+3）。零回归测试 `test_rules_none_zero_regression`、
  `test_presets_equal_v25_no_new_categories` 均通过。

## 4. 验收

- [x] `可能不可行` / `搞不好会失败` / `也许会有问题` 中 hedge 被保留，无语义翻转。
- [x] `或许不完全成立` 中 或许 仍被删除（不误保）。
- [x] 语义剪枝仅删「离题且低信息」句，离题含实质句保留。
- [x] `rules=None` 行为与 v2.5 字节级一致；`PRESETS` 仍为 5 类。
- [x] 全量 pytest 至全绿（188 passed）。
- [x] 提交为 Hyhyhyyy（无 Co-Authored-By），不触碰 nul/run.bat，未 push（远端对齐待用户决策）。

## 5. 备注

- 远端 git 对齐仍未解决：本地 main 自 v2.8 起未推送（与远程无共同祖先），push 需用户授权
  （force-push 本地 main 或 rebase 至新远程 tip 后正常 push），未经授权不执行。
