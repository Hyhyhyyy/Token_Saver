# SkillForge 技能资产标准规范 v1.0

> 本规范用于统一 AI 工作台中自定义 Skill（SKILL.md）的定义与描述格式，
> 目标是让 Agent 在每一轮对话中都能以更小的上下文代价、更高的准确率调度技能。

## 1. 为什么需要规范

在主流 Agent 工作台中，每个 Skill 的 `name` 与 `description` 会**常驻注入到每一轮对话的
"可用技能列表"** 中。这意味着：

- description 每多 1 个冗余 token，**每一个对话轮次**都重复付出该成本；
- 描述语义不统一（"当用户…"/"使用本技能"/"Use this skill"混用）、触发场景缺失，
  会让 Agent 调度时出现**识别偏差、误触发、协同紊乱**；
- 同一意思用 `description` / `description_zh` / `description_en` 重复表达，既浪费 token
  又可能造成语义冲突。

**量化公式**：会话总节省 ≈ Σ(各技能 description 清洗后减少的 token) × 会话轮次。

## 2. 标准 SKILL.md 模板

```markdown
---
name: <skill-id>            # 必须：kebab-case，与目录名一致
description: <用途一句话>。触发场景：<场景1>；<场景2>；<场景3>。
---

# <技能标题>

<正文：仅保留核心流程与资源引用，细节放入 references/，模板放入 assets/>
```

### description 推荐模板

```
<用途一句话>。触发场景：<场景1>；<场景2>；<场景3>。
```

示例：

```
将本地 Office/WPS 文档实时读写为可编辑内容。触发场景：用户要打开/编辑 docx、xlsx、pptx 等本地文件；需要所见即所得地修改并保存。
```

## 3. 字段约束

| 字段 | 必填 | 约束 |
|------|------|------|
| `name` | 是 | kebab-case（小写字母/数字/连字符），长度 1–48，与目录名一致 |
| `description` | 是 | 单一职责，含用途陈述 + 触发场景；Token ≤ 90（目标 ≤ 40） |
| `agent_created` | 推荐 | 由 Agent 创建的技能置 true，便于后续管理 |
| `version` / `author` 等 | 可选 | 非调度相关，可保留但不应冗长 |

> 不鼓励 `description_zh` / `description_en` 等重复语义字段；翻译/扩展放入正文或 `references/`。

## 4. 校验维度（三轴）

1. **格式（Format）**：YAML 可解析、必填字段存在、`name` 命名与目录一致。
2. **语义（Semantic）**：description 含明确用途与触发场景；聚焦单一职责，避免"还能做 X"。
3. **冗余（Redundancy）**：Token 不超预算；无营销废话（强大的/一站式/seamless…）；
   无重复短语；无重复语义字段；正文精简（细节移入 references/）。

## 5. 健康度评分

- 基准 100，每处 error −18、warning −6、info −2；
- < 60 为「异常」，60–89 为「待优化」，≥ 90 为「合规」。

## 6. 清洗流水线

- **Stage 1（规则，确定性）**：字段归一 → 填充词移除 → 触发场景标准化 → 重复字段合并 → 按 Token 预算压缩。
- **Stage 2（可选 LLM）**：配置 `LLM_API_URL` / `LLM_API_KEY` 后做语义级重写，进一步压到目标预算。

清洗结果经审阅后可「一键应用」，原文件自动备份为 `SKILL.md.bak`。
