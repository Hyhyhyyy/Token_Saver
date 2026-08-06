# SkillForge · 技能精炼台

> 面向个人开发者的 **Skill 资产优化工作台**：统一格式校验 · 语义清洗 · 冗余压缩 · 调用效果追踪，
> 引导 Agent 更精准地调用技能，**降低 AI 工作台每轮对话的无效 Token 开销**。

## 痛点

AI 工作台中存量自定义 Skill 普遍存在：描述格式混乱（字段各异）、表述冗余（长句堆砌、
营销废话）、语义不统一（中英文/人称混用、触发场景缺失）。由于 `description` 会**常驻注入每一轮对话**，
这些问题直接导致：无效 Token 持续放大 + Agent 调度识别偏差 + 多技能协同紊乱。

## 解决方案

一个以小型个性化工作台形式部署的 Web 应用：

- **统一格式校验**：按《SkillForge 标准规范 v1.0》三轴（格式 / 语义 / 冗余）自动体检，给出健康度评分与修复建议。
- **语义清洗**：规则引擎将混乱描述归一为标准模板 `<用途>。触发场景：a；b；c。`，移除填充词与重复字段；可选 LLM 语义重写进一步压缩。
- **冗余压缩**：以 Token 预算（目标 ≤40，硬上限 90）压减 description，前后对比量化节省。
- **调用效果追踪**：SQLite 记录每次优化/应用事件，数据看板展示累计节省、每轮常驻节省、节省趋势与技能排行。

## 快速开始

### 方式一：Docker（推荐）

```bash
# 修改 docker-compose.yml 中 ~/.workbuddy/skills 为本机 skills 目录
docker compose up -d
# 打开 http://localhost:8000
```

### 方式二：本地一键启动

```bash
chmod +x run.sh
./run.sh
```

### 方式三：手动

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SKILLS_DIRS=$HOME/.workbuddy/skills
uvicorn skillforge.server:app --host 0.0.0.0 --port 8000
```

## 配置项（环境变量）

| 变量 | 说明 | 默认 |
|------|------|------|
| `SKILLS_DIRS` | 待扫描的 skills 目录（分号/冒号分隔） | `~/.workbuddy/skills` + 项目 skills |
| `DATA_DIR` | SQLite 与数据存放目录 | `./data` |
| `LLM_API_URL` / `LLM_API_KEY` / `LLM_MODEL` | 可选，开启 LLM 语义重写 | 未配置则仅规则清洗 |

## 使用流程

1. 打开工作台，左侧列出全部 Skill 及其健康状态。
2. 选中技能 → **校验** 查看问题清单与建议。
3. 切到 **清洗** → 运行清洗，查看前后对比与 Token 节省 → **应用并写回**（原文件自动备份 `.bak`）。
4. 切到 **数据看板** 查看累计节省、每轮常驻节省与趋势排行。

## 目录结构

```
skill-forge/
├── skillforge/        # 后端：解析/校验/清洗/追踪/服务
│   ├── config.py  tokenizer.py  spec.py
│   ├── skill_parser.py  validator.py  cleaner.py  tracker.py  server.py
├── frontend/          # 可视化工作台（原生 HTML/CSS/JS，零构建）
│   ├── index.html  style.css  app.js
├── spec/STANDARD.md   # 标准规范文档
├── Dockerfile  docker-compose.yml  run.sh  requirements.txt
```

## 效果度量

会话总节省 ≈ Σ(各技能 description 清洗后减少的 token) × 会话轮次。
例如 20 个技能各压缩 30 token，则每轮省 600 token，千轮会话省约 60 万 token。
