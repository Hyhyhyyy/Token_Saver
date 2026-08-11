# PRD · evo2-12 规则检测增强（Prompt Simplifier）

> 版本：`2.12.0-evo` · 日期：2026-08-11 · 主理人：齐活林（Lead 直接落地，subagent 沙箱 499 失败约定）

## ① 背景与目标
v2.11 已完成「模式差异可见 + 第一人称自指 + 16 类可枚举」。用户进一步要求
**「进一步强化规则的检测效果」**——即在零回归硬契约（`rules is None` ≡ v2.5，
`PRESETS` 始终保持 5 基础类）不被破坏的前提下，提升各规则对冗余的**召回率**，
并补上此前完全未覆盖的一类噪声：**客套 / 寒暄礼貌冗余**。

## ② 硬约束（继承）
- `rules=None` 路径逐字等于 v2.5；**5 个基础规则**（politeness / role_prefix /
  empty_items / duplicate_lines / blank_lines）的词表**一律不改动**。
- 所有新增 / 增强均落在 **explicit-only 规则**（不进 `PRESETS`）。
- 零新增 pip 依赖；零构建前端；提交仅 Hyhyhyyy，无 Co-Authored-By，不推送。
- 不触碰 `nul` / `run.bat`。

## ③ 变更清单
### 3.1 新增规则 `courtesy_boilerplate`（explicit-only，仅激进预设）
移除无信息量客套噪声，分五组（长词优先，避免残留孤立「你」）：
- 招呼：你好 / 您好 / 在吗 / 嗨 …
- 道歉：对不起 / 抱歉 / 不好意思 / 打扰了 …
- 感谢：谢谢 / 感谢 / 辛苦了 / 麻烦了（含整体删「谢谢你 / 感谢你」）
- 客套求助（条件式）：如果可以的话 / 如果方便的话 …
- 结尾套话：仅供参考 / 不吝赐教 / 敬请谅解 / 如有问题 / 请知悉 …

**执行顺序设计**：`courtesy_boilerplate` 置于 `politeness` **之前**，
使「感谢你 / 谢谢你」作为整体单元移除（否则 politeness 先拆「感谢」会残留孤立「你」）。
与 `politeness` 互补：politeness 负责「请 / 麻烦 / 帮我」等指令语气词，
本规则只收纯礼貌套话；二者可同开、互不替代、不重复计数。

### 3.2 现有 explicit-only 规则词表召回扩展
| 规则 | 新增检测词（示例） |
|---|---|
| `hedging` | 未免 / 大抵 / 搞不好 / 十有八九 / 保不齐 / 大致上 |
| `redundant_adverbs` | 格外 / 分外 / 尤为 / 着实 / 甚为 / 倍加 / 异常 |
| `meta_comment` | 说真的 / 坦白说 / 直白地说 / 实话实说 / 简言之 |
| `logical_connector` | 在此基础上 / 即便如此 / 从而 / 由此 / 就这点而言 |
| `first_person` | 我以为 / 我寻思 / 代我 / 依我之见 / 拿我来说 / 就我而言 |

均保留既有护栏（否定前瞻 `_NEG_LOOKBEHIND`、区分性保护、条件标记永不进连接词集）。

### 3.3 `punctuation_normalize` 增强
标点周围空格归一化从「仅半角 `\s`」扩展为**半角 + 全角空格（U+3000）**，
显式用字符类 `[ \t\u3000]` 避免跨 Python 版本 `\s` 对全角空格匹配的歧义。
`你好　，　世界。` → `你好，世界。`

### 3.4 前端
- `SIMPLIFY_RULE_IDS` 增加 `courtesy_boilerplate`（共 **17 类**）。
- `SIMPLIFY_PRESETS.aggressive` 加入 `courtesy_boilerplate`（激进 = 保守 ∪ 6 类更深裁剪）。
- `RULE_META` 新增该规则元数据；`index.html` 新增对应勾选框。
- localStorage key 升级 `v2_12`。

## ④ 测试
- `test_all_rule_ids_exact` 更新为 17；`test_new_rule_ids_registered_not_in_presets`
  增加 `courtesy_boilerplate`。
- 新增 10 个用例覆盖：courtesy 移除 / 单元移除 / explicit-only / 道歉保留；
  hedging·redundant_adverbs·meta_comment·logical_connector·first_person 召回扩展；
  全角空格归一化。
- 全量 **185 passed**（v2.11 为 175）。

## ⑤ 验收示例（aggressive 预设）
`你好，请给我写个爬虫，如果可以的话帮我处理好反爬，谢谢，辛苦了。`
→ `，写个爬虫，处理好反爬，。`（招呼 / 请 / 给我 / 客套求助 / 感谢 全部清除）
