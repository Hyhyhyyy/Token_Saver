# 架构设计 · SkillForge 通用 Prompt 简化器（增量 evo2-9 · 本地语义压缩）

> 叠加于 v2.8（13 类规则）之上；版本 `2.9.0-evo`。
> 硬契约：`rules is None` 仍走 `PRESETS`（v2.5 五基础类），`simplified_text` 逐字等于 v2.5；任何 v2.9 行为不得改变该路径。
> 零新增 pip 依赖；前端零构建；接口向后兼容。

## 1. 设计取向（与 PRD 对齐）
- **抽取式，非抽象重写**：复用项目本地 `scorer.py` 的 `EmbeddingBackend`（local-st provider，v2.2 落地），做近义/重复句**折叠**，不做 LLM 生成式摘要（违背确定性/免费/隐私优先）。
- **explicit-only**：`semantic_compress` 为独立 id，`default_in_presets: False`，`PRESETS` 保持 5 基础类不变；`ALL_RULE_IDS` 13 → **14**。
- **稠密后端门控 + 优雅回退**：仅当 `get_vectorizer()` 返回**稠密** `EmbeddingBackend`（本地 embedding 服务可用）时真正折叠；否则（local-tfidf / 端点不可达 / 异常）**静默跳过**，返回原文、count=0、不 500、不抛未捕获异常。

## 2. 文件改动清单
| 文件 | 改动 |
|---|---|
| `skillforge/prompt_simplifier.py` | ① 常量 `_SEMANTIC_THRESHOLD_DEFAULT=0.90`/`MIN=0.80`/`MAX=0.98`、`_SEMANTIC_PRUNE_FLOOR=0.60`、`_SEMANTIC_PROTECT_HINTS`；② `ALL_RULE_IDS`+`CANONICAL_ORDER` 末位追加 `semantic_compress`；③ `RULE_REGISTRY` 注册（explicit-only）；④ 新增 `_get_semantic_backend()`（lazy import scorer + `is_dense_backend` 门控）、`_strip_protect_tokens()`、`_cosine_dense()`、`_rule_semantic_compress(work, aggressive_like, explicit, threshold, prune, backend=None)`；⑤ `simplify_prompt` 增 `semantic_threshold`/`semantic_prune` 参数与 `_semantic_threshold_clamp`；⑥ 主循环在 `punctuation_compress` 后插入 `semantic_compress` 分支（仅 `_tag(..., explicit)`）。 |
| `skillforge/scorer.py` | `EmbeddingBackend` 增公开 `vectorize(text)`（薄封装 `_emb`，复用实例缓存）——PRD 误称的 `vectorize()` 实际缺失，此为「极小增强」。 |
| `skillforge/__init__.py` | 版本 `2.8.0-evo` → `2.9.0-evo`。 |
| `skillforge/server.py` | `/api/simplify` 读取可选 `semantic_threshold`/`semantic_prune`，透传 `simplify_prompt`（非 list 字段不影响 `rules=None` 契约；越界/非法静默回落默认）。 |
| `frontend/app.js` | `SIMPLIFY_RULE_IDS` 13→14；`getSimplifyState` 附带 `semantic_threshold`/`semantic_prune`（仅勾选时）；`localStorage` 升 `v2_9` 并迁移 `v2_8`；`doSimplify` 下发两参数；滑块/剪枝开关 change 监听。 |
| `frontend/index.html` | 进阶精简组新增 `data-rule="semantic_compress"` 复选框 + 阈值 `<input type=range min=0.80 max=0.98 step=0.01 value=0.90>` + 剪枝 `<input type=checkbox id=semPrune>`。 |
| `tests/test_simplify_rules.py` | `test_all_rule_ids_exact` 14；新增 `test_semantic_*` 8 项（近义折叠/异主题保留/高阈值/零回归/embedding 回退/组合/剪枝）；`test_semantic_threshold_clamp`。 |

## 3. 数据流（语义压缩分支）
```
simplify_prompt(text, rules=[...,"semantic_compress"], semantic_threshold=0.90, semantic_prune=False)
  → explicit=True（rules 非 None）
  → 主循环（保护→各规则→_restore）后插入：
      if "semantic_compress" in rule_ids:
          th = _semantic_threshold_clamp(semantic_threshold)   # 0.80–0.98 兜底
          work, n = _rule_semantic_compress(work, ..., threshold=th, prune=bool(semantic_prune))
          if n: changes.append("折叠 N 处语义重复句 [semantic_compress]")
  → _rule_semantic_compress:
      1. backend = _get_semantic_backend()  # None ⇒ 跳过（返回 work,0）
      2. 按句切分（占位符原子化）；<2 句 ⇒ 跳过
      3. backend.vectorize(逐句去占位符文本)  # 任一失败 ⇒ 整规则跳过
      4. 能力1：两两余弦 ≥ threshold ⇒ 保留首次、折叠后续
      5. 能力2（prune=True）：与任一句最高相似度 < _SEMANTIC_PRUNE_FLOOR 且无指令/条件/代码/否定标记 ⇒ 折叠
      6. 折叠数 >0 ⇒ 返回 "".join(保留段), folded
```

## 4. 任务列表（按实现顺序）
1. `scorer.py`：`EmbeddingBackend.vectorize` 公开化（低风险增强）。✅
2. `prompt_simplifier.py`：常量 + 规则注册 + `_rule_semantic_compress` + 主循环分支 + 签名扩展。✅
3. `server.py`：解析并透传 `semantic_threshold`/`semantic_prune`。✅
4. 前端：`SIMPLIFY_RULE_IDS`/`index.html`/`app.js`（滑块 + 剪枝 + localStorage 迁移）。✅
5. 测试：id 列表 + 8 项专项 + clamp。✅
6. 全量回归：159 passed。✅

## 5. 待明确事项（已拍板，见 PRD §⑤）
- **Q1**：`semantic_compress` explicit-only，**不进**任何预设（前端保守/激进均不默认勾选）。
- **Q2**：阈值默认 0.90、区间 0.80–0.98（接受）。
- **Q3**：重要性剪枝默认**关闭**（`semantic_prune=False`），前端默认不勾。

## 6. 已知限制 / 后续
- 语义压缩**依赖本地 embedding 服务**（ollama / nomic-embed-text 等 OpenAI 兼容端点）。未部署时自动跳过——这是「隐私/离线优先」定位的代价，也是 P0-3 要求的优雅降级。
- 折痕质量上限受限于本地 embedding 模型；阈值滑块交由用户按语料调参。
- `data/vectorizer.json` 若指向 `local-st` 且端点可达即启用；否则回退 local-tfidf → 跳过语义压缩。
