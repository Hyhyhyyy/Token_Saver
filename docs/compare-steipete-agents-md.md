# 对比：SkillForge Prompt Simplifier vs `steipete/agent-scripts` 的 `AGENTS.MD`

> 对比时间：2026-08-11 · 参照：https://github.com/steipete/agent-scripts/blob/main/AGENTS.MD
> 结论先说：二者**不是竞品，是互补**。AGENTS.MD 教 agent「怎么写好」；SkillForge 把「喂给 agent 的 prompt 压瘦」。

## 0. 一句话定性（先澄清误读）
- **`AGENTS.MD`（steipete）**：agent 的**行为宪法**。用自然语言写下「沟通风格 / 任务路由 / Git 身份 / 保密边界 / PR·CI 流程」等硬规则，由 LLM 理解后自行执行。它**不修改任何文本**，只是约束 agent 自己的产出。
- **SkillForge Prompt Simplifier**：**机械式 prompt 压缩器**。用确定性正则规则检测并删除 prompt 中的冗余（礼貌/寒暄/弱语气/冗余副词/连接词/标点…），目标是省 token。
- 二者在**不同层**：AGENTS.MD = agent 层（怎么写）；SkillForge = pipeline 层（怎么压）。把 SkillForge 当成「自动 AGENTS.MD 压缩器」是误用。

## 1. 本质对比表
| 维度 | `AGENTS.MD`（steipete） | SkillForge Simplifier |
|---|---|---|
| 所在层 | agent 行为 / 输出风格 | prompt 预处理（输入侧） |
| 作用机制 | 自然语言规则，LLM 理解后执行 | 确定性正则，代码执行 |
| 主要目标 | 让 agent 产出「有 substance 的好沟通」 | 削减 prompt 冗余、省 token |
| 一致性保证 | 软（依赖模型当次判断，不可审计） | 硬（逐次一致，输出 `changes` 可审计） |
| 零回归契约 | 无此概念 | 有（`rules=None` ≡ v2.5，PRESETS 恒 5 基础类） |
| 处理对象 | agent **自己的回复** | **任意用户输入**的 prompt |
| 误删风险 | 无（不改文本） | 有（靠否定前瞻 / 保护占位符 / 区分性护栏兜住） |
| 可量化收益 | 无（风格层面） | 有（tokens_saved / savings_pct） |

## 2. 关键张力：「简洁」vs「有 substance」
`AGENTS.MD` 的 Communication 段明确写道：
- *"Prefer useful substance over artificial brevity."*（宁可保留有用实质，也不要人工式的简短）
- *"Avoid list-shaped answers by default… Prefer one clear recommendation and 2–5 short supporting paragraphs."*（反对把什么都压成列表/短句）

而 SkillForge 的 **aggressive** 模式恰好在做「artificial brevity」：删 `也许/非常/你好/谢谢/因此/需要注意的是`。

**但二者可共存**，因为管的是不同面：
- AGENTS.MD 约束 **agent 的回复**（输出侧）；
- SkillForge 压缩 **喂给模型的 prompt**（输入侧）。

**真实冲突点（值得 SkillForge 警惕）**：
- SkillForge 的 `hedging` 规则删 `也许/大概/恐怕` → 可能抹掉**诚实的不确定性信号**。例如「这个方案可能不可行」被压成「这个方案不可行」，语义翻转。
- AGENTS.MD 反而要求 agent **校准置信度**、点出有趣的根因——它欢迎带条件的谨慎表达。
- 这恰好是我们 v2.11 已做的「保留『应该』强约束」议题的延伸：**弱语气的删除必须保护承载关键语义的「可能 + 条件/负面」结构**，不能一味扩词表。

## 3. 覆盖能力对照（谁擅长什么）
- **SkillForge 擅长**：确定性删礼貌/寒暄/弱语气/冗余副词/连接词/标点；可审计；token 量化；批量预处理。
- **SkillForge 不擅长**（恰是 AGENTS.MD 关注却靠模型判断的）：语义级冗余、substance 平衡、保密/身份边界、何时该 verbose。
- **AGENTS.MD 擅长**：靠模型判断「该简还是该详」；安全合规（secrets/identity 边界）。
- **AGENTS.MD 不做**：机械压缩、token 节省、对用户输入的批量预处理。

## 4. 可借鉴点（给 SkillForge 的下一步）
1. **语义压缩已是桥梁**：我们已有 `semantic_compress`（本地 embedding 近义折叠 + 可选重要性剪枝），正对应 AGENTS.MD 的「substance」观——它 beyond 表层 lexicon。加强它（而非扩词表）更接近「保留 substance」。
2. **hedging 的「诚实不确定性」护栏**：参考 AGENTS.MD 对置信度校准的重视，把「可能 + 负面/条件」结构标记为**保留**（在既有否定前瞻之外再加语义护栏），避免语义翻转。这是 v2.13 高价值方向。
3. **「结论先行」重排（可选/P2）**：AGENTS.MD 要 *lead with the conclusion*。可作显式 reorder 规则，但需谨慎——我们当前契约是「无损裁剪不重排」，故低优先。
4. **结构合理化（P2）**：AGENTS.MD 要 *bullets only for genuinely enumerable items*。我们 `duplicate_lines/clauses` 只去冗余、不强制结构，可加「列表规范化」显式规则。
5. **安全冻结已对齐**：SkillForge 的「含『请』安全词冻结 + 代码/URL 占位符保护」与 AGENTS.MD 的 secrets/identity 边界精神一致——都不动敏感内容。

## 5. 结论
- 不是竞品，是**互补**：AGENTS.MD 教 agent 写好；SkillForge 把喂给 agent 的 prompt 压瘦。
- 正确用法：SkillForge 处理**用户输入侧**，AGENTS.MD 类规则管 **agent 输出侧**；两者串联可同时省 token 且保质量。
- 最该从 AGENTS.MD 吸收的：**把「保留 useful substance / 诚实不确定性」作为 `hedging`/`redundant_adverbs` 的更高优先级护栏**，而非一味扩词表——这应是 v2.13 的主线。
