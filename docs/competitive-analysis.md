# 竞品区分度分析 · SkillForge「通用 Prompt 简化器」（市场调研）

> 范围：仅限「通用 Prompt 简化器」这条产品线（规则式 prompt 文本压缩）。
> 关联提及：cleaner / SKILL.md 清洗仅作为「集成工作台」差异化背景，不展开。
> 当前状态：v2.8 进行中，共 **13 类规则**（v2.6 的 9 类 + v2.7 的 `logical_connector`/`filler_particles` + v2.8 的 `duplicate_clauses`/`punctuation_compress`）。
> 本文为**纯文档分析，不涉及代码改动**。
> 数据来源与核实注记见文末附录；凡与初步调研不一致处已显式标注。

---

## 执行摘要（Executive Summary）

1. **赛道分层清晰**：prompt 压缩不是单一品类，而分四层——① 语义 ML 压缩（LLMLingua、The Token Company、TokenShift）、② Agent 行为 Skill（Ponytail、Caveman）、③ 优化/质量 SaaS（PromptPerfect）、④ 框架/网关/厂商特性（LangChain、各家 prompt caching）。SkillForge 属第 ① 层的**确定性规则子集**，与 ② 层不在同一平面。
2. **SkillForge 的真实护城河 = 隐私 / 离线 / 免费 / 确定性 / 零依赖 / 即时 / 可复现 / CJK 偏重 + 集成工作台**。这在一个"隐私优先本地小众"细分市场里有真实区分度。
3. **但作为"通用 token saver"不具压倒竞争力**：比率远低于 LLMLingua 类语义压缩器（2–5× 对我们有时仅 10–40% 视冗余），也未切入 Ponytail/Caveman 占位的"运行时 Agent 省 token"心智；且完全未碰"缓存"这一零质量风险、50–90% 折扣的最强省钱路径。
4. **关键认知修正**：行为 Skill 赛道的"省 token"叙事被显著高估——Caveman 官方宣称 65% 输出 token，独立实测（SkillsBench 86 任务 / 240 跑）仅 **~8.5%** 全量节省。这意味着"填充词/话术压缩"类工具的真实杠杆有限，SkillForge 应**诚实定位、不夸大比率**，以"确定性 + 可复现 + 免费"对抗对手的炒作。
5. **建议路线**：P0 补"可选语义压缩模式（本地小模型、opt-in、保隐私）"与"Agent 行为 Skill 导出"夺回心智；P1 补"缓存提示"与"成本/质量看板"；P2 补多语言与分发形态。

---

## 1. 竞品矩阵

维度说明：压缩方式 / 是否需联网 API / 是否本地离线 / 是否确定性 / 隐私（数据出境风险）/ 零依赖（无重型运行时）/ 免费 / 支持语言 / 宣称节省率 / 附加能力。

| 产品 | 压缩方式 | 联网 API | 本地离线 | 确定性 | 隐私 | 零依赖 | 免费 | 语言 | 宣称节省率 | 附加能力 |
|---|---|---|---|---|---|---|---|---|---|---|
| **SkillForge 简化器**（我方） | 规则式（regex+词典，13 类） | 否 | ✅ | ✅ | 优（不出本机） | ✅（仅 stdlib） | ✅（OSS） | CJK 偏重 | 无统一宣称；高冗余中文实测约 10–40%，短 prompt 偏下限 | 集成工作台（格式校验/语义清洗/压缩/效果追踪） |
| **Ponytail**（`DietrichGebert/ponytail`） | Agent 行为 Skill（注入 YAGNI 决策阶梯，运行时改"写多少"） | 否（本地 skill + 可选 node hooks） | ✅ | ❌（模型行为受注入影响） | 优 | 近零（hooks 需 node） | ✅（MIT） | 宿主无关（14+ agent） | 官方基准：代码 −54% 均 / −94% 峰、成本 −20%、速度 +27%（**自报，第三方实测存疑**） | `/ponytail-review`/`audit`/`debt`；GitHub Trending 2026-08；~2.5 万 stars |
| **Caveman**（`JuliusBrussee/caveman`） | Agent 行为 Skill（输出压缩为"电报体"，运行时） | 否 | ✅ | ❌ | 优（MIT，无上传） | ✅ | ✅（MIT） | 英文风格为主（中文弱） | 官方 65% 输出 token；**独立实测仅 ~8.5% 编码全量** | lite/full/ultra/wenyan 四档；`/caveman-*`；记忆压缩 `cavemem`；~8.3 万 stars |
| **LLMLingua 家族**（Microsoft） | 语义 ML（困惑度/SLM 抽取式） | 否（可自托管） | ✅（需算力） | 近似（依 compressor） | 优（可全本地） | ❌（torch+模型权重） | ✅（MIT，OSS） | 多语（英文最佳） | **最高 20×（RAG 上下文）；指令 prompt 实测 2–5×** | LLMLingua / LLMLingua-2 / LongLLMLingua；保语义；研究 SOTA |
| **The Token Company**（YC W26） | 语义 ML（bear-1 分类，非生成） | ✅（默认云；企业可 on-prem/VPC） | ❌（默认）/ 企业可选 | ✅（确定性分类） | 中（云端；企业可数据驻留） | ✅（API） | ❌（$0.05/1M 移除 token） | 多语 | 10–40% @ 满精度（官方） | 盲测准确率 +5%；<100ms/100K tokens；drop-in 中间件；**唯一可信独立商用 API** |
| **TokenShift**（PointFive） | 端点本地（coding-agent 流量 ML 分类） | 否 | ✅ | ✅ | 优 | ❌（需装端点） | ❌（商业） | 英文（coding） | 12–21% | 治理/可见性；CLI 输出/构建日志/截图压缩 |
| **PromptPerfect / Prompt Optimizer** | 优化/质量（重写提清晰度/结构，顺带更短） | ✅ | ❌ | ❌ | 中 | ❌ | ❌（$9.99/mo SaaS + Chrome 插件） | 多语 | 非主打（顺带更短） | 质量/结构优化；面向非技术用户 |
| **LangChain ContextualCompressionRetriever** | 框架/网关（检索上下文压缩） | 取决于 LLM | 可本地 | ❌ | 中 | ❌（需 LangChain） | ✅（OSS） | 多语 | 依实现 | RAG 检索压缩；生态集成 |
| **Anthropic / OpenAI Prompt Caching** | 缓存（重复前缀折扣，非压缩） | ✅ | ❌ | ✅ | 依厂商 | ✅（原生特性） | ✅（特性） | 全 | 缓存命中 **50–90%** 输入折扣 | 零质量风险；原生；最强省钱组合一环 |

---

## 2. 区分度评分卡

### 2.1 优势（我方）

| 优势 | 说明 | 相对谁成立 |
|---|---|---|
| 确定性 | 同输入同输出，可审计、可回归 | 对所有 ML/行为类（LLMLingua/Ponytail/Caveman/The Token Company 云变体） |
| 免费 | 开源、无按量计费 | The Token Company / TokenShift / PromptPerfect |
| 隐私 | 数据不出本机 | 所有云端 API（The Token Company 默认云、PromptPerfect） |
| 离线 | 无需网络 | 同上 + LangChain/PromptPerfect |
| 零依赖 | 仅 Python stdlib | LLMLingua（torch+GPU）、TokenShift（端点）、LangChain |
| 即时 | 毫秒级、无模型加载 | LLMLingua（需加载 compressor）、The Token Company（网络延迟） |
| 可复现 | 规则固定，结果稳定 | 行为 Skill（受模型随机性影响） |
| 集成工作台 | 格式校验/语义清洗/压缩/效果追踪一体 | 所有单点压缩工具（均无资产治理闭环） |

### 2.2 劣势（我方）

| 劣势 | 影响 | 严重程度 |
|---|---|---|
| 无语义压缩（比率远低于 LLMLingua 类） | 对长 RAG/冗余上下文，省 token 能力弱于语义 ML（2–5× vs 我们 10–40% 视冗余） | 高（核心比率短板） |
| 无 Agent 行为集成（错失 Ponytail 心智份额） | "运行时省 token"叙事被 Ponytail/Caveman 抢占，用户心智不在我方 | 高（心智/触达） |
| CJK 偏重 | 英文 prompt 覆盖弱，国际受众受限 | 中 |
| 英文 filler 缺失 | 英文冗余清理不全，削弱跨语种价值 | 中 |
| 无缓存提示 | 未引导用户用原生缓存（50–90% 折扣、零质量风险），错失最强省钱路径 | 高（低投入高回报缺口） |
| 缺质量度量看板 | 无 before/after token + 估算成本 + 质量保全，可信度与留存弱 | 中 |
| 分发弱 | 仅 Web 工作台，无 CLI/VS Code/npm，触达低 | 中 |

---

## 3. 竞争力裁定（Verdict）

**结论：SkillForge 简化器在「隐私优先 / 本地 / 免费 / 确定性 / 可复现 / CJK」这一细分市场有真实、可防御的区分度；但作为"通用 token saver"，对 LLMLingua 类语义压缩器与 Ponytail 类行为 Skill 均不具压倒竞争力。不应定位为"最强省 token 工具"，而应定位为"最可信的本地确定性冗余清理器 + Skill 资产优化工作台"。**

理由：

- **vs 语义 ML 压缩（LLMLingua / The Token Company）**：比率层面我们明显落后（LLMLingua 指令 prompt 2–5×、RAG 上下文最高 20×；我们视冗余 10–40%）。但我们在确定性/免费/隐私/离线/零依赖全面胜出；LLMLingua 需 torch+GPU+模型权重、门槛与"即时"相悖，The Token Company 需联网且按量付费。→ **我们赢"可信赖的本地轻量"场景，输"极限压缩比"场景。**
- **vs 行为 Skill（Ponytail / Caveman）**：它们占"省 token"开发者心智，但是运行时注入、非确定性、且真实节省被高估（Caveman 实测 8.5%）。SkillForge 是静态预处理、确定性、可复现——**我们更诚实、更可审计**，但错失"Agent 自动省"的心智与集成。→ **我们赢"可解释/可回归"场景，输"心智份额/运行时自动化"场景。**
- **vs 缓存（Anthropic/OpenAI Prompt Caching）**：缓存命中 50–90% 输入折扣、零质量风险，是比压缩更优的省钱路径。SkillForge **完全未涉足**——这是最明显的结构性短板，且补齐成本极低（仅提示+检测）。
- **综合**：行业定性（pointfive 2026）明确指出"prompt 压缩基本还不是真正的商业品类，可信独立商用 API 基本只有 The Token Company，多数仍是 OSS 研究或网关/框架特性；最强省钱组合是缓存优先 + 压缩补刀"。SkillForge 处于"OSS 研究/规则式"象限，应以差异化（隐私/确定性/集成）而非比率参与竞争。

---

## 4. 迭代路线图（按优先级）

| # | 举措 | 优先级 | 预期区分度增益 | 说明 |
|---|---|---|---|---|
| ① | **可选语义压缩模式**（本地小模型优先，opt-in，保隐私，不靠云 API） | **P0** | 高（正面补"比率短板"，刚 LLMLingua/The Token Company 的高比率叙事，同时守住隐私/离线） | 默认关，用户显式开启；本地 SLM（如小 encoder）做抽取式压缩，复用现有保护机制；不进 PRESETS，契约安全 |
| ② | **Agent 行为 Skill 导出 / 注入**（或文档化"简化器 + 懒 agent"组合） | **P0** | 高（切入 Ponytail 车道，夺回"省 token"心智） | 把 13 类规则导出为 Claude Code/Codex 等 agent 的 Skill/钩子；或产出"先简化再交给 agent"的标准组合文档 |
| ③ | **Prompt 缓存提示**（检测重复静态前缀，建议开原生缓存） | **P1** | 高（低投入蹭 50–90% 折扣，补最强省钱路径缺口） | 静态分析输入，识别可缓存前缀并提示用户配置 Anthropic/OpenAI caching；零质量风险 |
| ④ | **Before/After Token + 估算成本 + 质量保全看板** | **P1** | 中高（补"缺质量度量看板"劣势，提升可信度与留存） | 结果区展示 token 节省、估算 $、变更类别溯源；标注"未改动代码/指令"以保全质量证据 |
| ⑤ | **多语言扩展（英文 filler 变体）** | **P2** | 中（补"英文 filler 缺失 / CJK 偏重"劣势，扩受众） | 增补英文语气/填充/连接词表；面向 coding-agent 英文 prompt |
| ⑥ | **分发形态（CLI / VS Code 插件 / npm）** | **P2** | 中（补"分发弱"劣势，提升触达） | 把 Web 工作台能力封装为 CLI / 插件，融入开发者工作流 |

> 优先级逻辑：P0 直击两个"高严重度"短板（比率、心智）；P1 以低投入补"最强省钱路径"与"可信度"；P2 扩受众与触达。

---

## 5. 定位话术建议（面向用户）

**我们是谁（Positioning）：**
> "SkillForge 简化器是一款**本地、免费、确定性、零依赖**的 prompt 冗余清理器，偏重中文，隶属于更宽的 **Skill 资产优化工作台**（格式校验 / 语义清洗 / 冗余压缩 / 调用效果追踪）。你粘贴一段 prompt，它**即时、可复现**地删掉填充词、逻辑连接词、语气词、完全重复与冗余标点——**数据不出本机，结果每次一致**，适合对隐私、可审计、离线有要求的个人与团队。"

**我们不为谁（Anti-persona）：**
> - 不为追求**极限压缩比**的人——那种场景请用 LLMLingua / The Token Company（语义 ML，比率更高）。
> - 不为想要**运行时 Agent 自动省 token**的人——那种场景请用 Ponytail / Caveman（行为 Skill，自动注入）。
> - 不为需要**云端 API、企业 SLA 或托管算力**的团队——我们坚持本地离线；语义模式也以本地小模型 opt-in 提供，不绑定云。

**一句话 slogan 候选：** "确定性地删掉废话，不删你的隐私——本地、免费、可复现的 prompt 冗余清理器。"

---

## 附录 · 数据来源与核实注记

**核实修正（与初步调研不一致处）：**
- **Caveman stars**：初步称"~80k"；多源核实为 **~8.3 万（82,990）**，由 19 岁荷兰学生 Julius Brussee 于 2026-04 创建，网站 caveman.so。
- **Caveman 节省率**：官方 65% 是**输出 token**（聊天场景）；独立实测（tahou.com，SkillsBench 86 任务 / 240 跑 / ~$106）全量编码任务仅 **~8.5%**，且质量无显著下降。文中已采用实测值。
- **Ponytail stars/基准**：核实 ~2.5 万 stars（2026-06 创建，v4.7.0），GitHub Trending 登顶 2026-08；成本/代码节省为**官方自报基准**，第三方（einverne）实测结论偏保守，文中标注"自报、存疑"。
- **LLMLingua 20×**：核实该数字为 **RAG 上下文上限**；指令 prompt 实测仅 **2–5×**。文中已区分。
- **The Token Company**：核实 YC W26、18 岁创始人 Otso Veistera、$0.05/1M 移除 token、bear-1 分类模型、<100ms/100K tokens、盲测准确率提升；与初步一致。
- **pointfive 2026 定性**：核实"基本非真正商业品类、唯一可信独立商用 API = The Token Company、强省钱组合 = 缓存优先 + 压缩补刀"等结论，与初步一致。

**主要来源**（检索于 2026-08-10）：
- Ponytail：everydev.ai/tools/ponytail；blog.yeyupiaoling.cn；www.einverne.info/post/887.html
- Caveman：opc.csdn.net（caveman 项目解读）；modb.pro；blog.mushroom.cv；www.tahou.com（独立实测 8.5%）
- LLMLingua：github.com/microsoft/LLMLingua；leanlm.ai/blog/prompt-compression；dreaming.press
- The Token Company：respan.ai/market-map/the-token-company；thetokencompany.com/pricing；extruct.ai
- pointfive 2026 指南：www.pointfive.co/guides/top-prompt-compression-solutions-2026
- 缓存：Anthropic / OpenAI 官方 prompt caching 文档（经 pointfive 引用：缓存命中 50–90% 折扣）
