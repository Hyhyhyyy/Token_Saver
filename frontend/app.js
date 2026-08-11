"use strict";

const state = { skills: [], current: null, clean: null };

const $ = (sel) => document.querySelector(sel);
const el = (tag, attrs = {}, html = "") => {
  const e = document.createElement(tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  if (html) e.innerHTML = html;
  return e;
};
const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

/* 复古环形分数（SVG，CSS 已做 stroke 过渡） */
function scoreRing(value, color) {
  const r = 34, c = 2 * Math.PI * r;
  const off = c * (1 - Math.max(0, Math.min(100, value)) / 100);
  return `<div class="score-ring">
    <svg width="84" height="84" viewBox="0 0 84 84">
      <circle class="ring-bg" cx="42" cy="42" r="${r}"></circle>
      <circle class="ring-fg" cx="42" cy="42" r="${r}" stroke="${color}"
        stroke-dasharray="${c.toFixed(1)}" stroke-dashoffset="${c.toFixed(1)}"></circle>
    </svg>
    <div class="ring-num" data-target="${value}">0</div>
  </div>`;
}

/* 数字滚动：把 [data-count] 元素从 0 动画到目标值 */
function countUpAll(root = document) {
  root.querySelectorAll("[data-count]").forEach((n) => {
    const target = parseFloat(n.dataset.count);
    const dec = (n.dataset.dec ? parseInt(n.dataset.dec, 10) : 0);
    const dur = 900, t0 = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - k, 3);
      n.textContent = (target * e).toFixed(dec);
      if (k < 1) requestAnimationFrame(step);
      else n.textContent = target.toFixed(dec);
    };
    requestAnimationFrame(step);
  });
  // 分数环数字滚动
  root.querySelectorAll(".score-ring .ring-num").forEach((n) => {
    const target = parseInt(n.dataset.target, 10) || 0, dur = 1000, t0 = performance.now();
    const fg = n.parentElement.querySelector(".ring-fg");
    const c = parseFloat(fg.getAttribute("stroke-dasharray"));
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      const e = 1 - Math.pow(1 - k, 3);
      n.textContent = Math.round(target * e);
      fg.setAttribute("stroke-dashoffset", (c * (1 - target * e / 100)).toFixed(1));
      if (k < 1) requestAnimationFrame(step);
      else { n.textContent = target; fg.setAttribute("stroke-dashoffset", (c * (1 - target / 100)).toFixed(1)); }
    };
    requestAnimationFrame(step);
  });
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), 2200);
}
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
  return r.json();
}

/* ---------- 初始化 ---------- */
async function init() {
  const [health, list] = await Promise.all([api("/api/health"), api("/api/skills")]);
  state.skills = list.skills;
  $("#meta").innerHTML =
    `分词器：${esc(health.tokenizer)}<br>已扫描技能：${list.count} 个`;
  renderSidebar();
  initSimplifier();     // v2.5：绑定简化器拖拽/按钮（一次绑定）
  if (list.count) selectSkill(list.skills[0].name).catch(() => {});
  // 使用说明：首次进入自动弹（不阻塞首屏渲染）
  initOnboarding();
}

function renderSidebar() {
  $("#skillCount").textContent = state.skills.length;
  const ul = $("#skillList"); ul.innerHTML = "";
  if (!state.skills.length) {
    ul.innerHTML = `<div class="guide-empty" style="padding:32px 12px">
      <div class="ge-emoji">🗂️</div>
      <div class="ge-title">还没扫描到技能</div>
      <div class="ge-text">SkillForge 会扫描本地 <b>skills/</b> 目录下所有带 <b>SKILL.md</b> 的技能包。<br>把技能放进该目录，然后<strong>刷新页面</strong>即可在此显示。</div>
    </div>`;
    return;
  }
  for (const s of state.skills) {
    const li = el("li", { class: "skill-item", "data-id": s.name });
    li.innerHTML =
      `<span class="nm">${esc(s.name)}</span>` +
      `<span class="tk">${s.desc_tokens}t</span>` +
      `<span class="badge ${s.status}">${s.status === "valid" ? "合规" : s.status === "warning" ? "待优化" : "异常"}</span>`;
    li.onclick = () => selectSkill(s.name);
    ul.appendChild(li);
  }
}

/* ---------- 选择技能 ---------- */
async function selectSkill(id) {
  state.current = id; state.clean = null;
  document.querySelectorAll(".skill-item").forEach((n) => n.classList.toggle("active", n.dataset.id === id));
  const d = await api(`/api/skills/${encodeURIComponent(id)}`);
  $("#empty").classList.add("hidden");
  $("#detailPanel").classList.remove("hidden");
  $("#d-name").textContent = d.name;
  $("#d-path").textContent = d.path;
  const sc = d.validation.score;
  $("#d-score").innerHTML = scoreRing(sc, sc >= 90 ? "var(--green)" : sc >= 60 ? "var(--amber)" : "var(--red)");
  renderOverview(d);
  renderValidate(d);
  $("#tab-clean").innerHTML = ""; $("#tab-track").innerHTML = "";
  switchTab("overview");
}

function renderOverview(d) {
  const v = d.validation;
  const fm = d.frontmatter || {};
  const keys = Object.keys(fm);
  const html = `
    <div class="card">
      <h3>资产概览</h3>
      <div class="kv"><span class="k">状态</span><span><span class="badge ${v.status}">${
        v.status === "valid" ? "合规" : v.status === "warning" ? "待优化" : "异常"
      }</span> · 健康度 <b data-count="${v.score}">0</b>/100</span></div>
      <div class="kv"><span class="k">description Token</span><span><b data-count="${d.desc_tokens}">0</b> （常驻每轮上下文）</span></div>
      <div class="kv"><span class="k">SKILL.md 总 Token</span><span data-count="${d.total_tokens}">0</span></div>
      <div class="kv"><span class="k">问题数</span><span><b data-count="${v.error_count}">0</b> 错误 / <b data-count="${v.warning_count}">0</b> 警告 / <b data-count="${v.info_count}">0</b> 提示</span></div>
      ${d.parse_error ? `<div class="kv"><span class="k">解析错误</span><span style="color:var(--red)">${esc(d.parse_error)}</span></div>` : ""}
    </div>
    <div class="card">
      <h3>当前 Frontmatter 字段 (${keys.length})</h3>
      ${keys.map((k) => `<div class="kv"><span class="k">${esc(k)}</span><span class="mono">${esc(String(fm[k])).slice(0, 200)}</span></div>`).join("")}
    </div>`;
  $("#tab-overview").innerHTML = html;
  countUpAll($("#tab-overview"));
}

function renderValidate(d) {
  const v = d.validation;
  let html = `<div class="card"><h3>校验结果 · ${v.issues.length} 项</h3>`;
  if (!v.issues.length) html += `<div style="color:var(--green)">✓ 未发现问题，符合标准规范。</div>`;
  for (const i of v.issues) {
    html += `<div class="issue ${i.severity}">
      <div><span class="sev">${i.severity}</span> <span class="code-chip">${esc(i.code)}</span> · <span class="mono">${esc(i.field)}</span> <span class="src-tag">${esc(i.source || "builtin")}</span></div>
      <div class="msg">${esc(i.message)}</div>
      <div class="sug">建议：${esc(i.suggestion)}</div>
    </div>`;
  }
  html += `</div>`;
  $("#tab-validate").innerHTML = html;
}

/* ---------- 清洗 ---------- */
async function runClean() {
  const useLlm = $("#useLlm")?.checked || false;
  const res = await api("/api/clean", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skill_id: state.current, use_llm: useLlm }),
  });
  state.clean = res;
  const saved = res.saved_tokens;
  const pct = res.before_desc_tokens ? Math.round((saved / res.before_desc_tokens) * 100) : 0;
  const html = `
    <div class="card">
      <h3>语义清洗 + 冗余压缩</h3>
      <label style="font-size:12px;color:var(--muted)"><input type="checkbox" id="useLlm"> 启用 LLM 语义重写（需配置 LLM_API_URL/KEY）</label>
      <div class="diff-stat">
        <div><div class="big">${res.before_desc_tokens}t</div><div class="l">清洗前</div></div>
        <div style="font-size:20px">→</div>
        <div><div class="big down">${res.after_desc_tokens}t</div><div class="l">清洗后</div></div>
        <div style="margin-left:auto;text-align:right"><div class="big down">-${saved}t</div><div class="l">节省 ${pct}%</div></div>
      </div>
      <div class="compare">
        <div class="cmp-box cmp-before"><h4>清洗前 description</h4><pre>${esc((state.skills.find(s=>s.name===state.current)?.frontmatter?.description) || "")}</pre></div>
        <div class="cmp-box cmp-after"><h4>清洗后 description</h4><pre>${esc(res.frontmatter.description)}</pre></div>
      </div>
      <div class="changes"><b>变更：</b><ul>${res.changes.map((c) => `<li>${esc(c)}</li>`).join("") || "<li>无需变更</li>"}</ul></div>
      <div class="row">
        <button class="btn" id="applyBtn">✓ 应用并写回文件</button>
        <button class="btn secondary" id="copyBtn">复制完整 SKILL.md</button>
      </div>
    </div>
    <div class="card"><h3>清洗后完整文件预览</h3><pre class="mono">${esc(res.serialized)}</pre></div>`;
  $("#tab-clean").innerHTML = html;
  $("#useLlm").onchange = runClean;
  $("#applyBtn").onclick = applyClean;
  $("#copyBtn").onclick = () => { navigator.clipboard.writeText(res.serialized); toast("已复制到剪贴板"); };
}

async function applyClean() {
  const res = await api("/api/apply", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ skill_id: state.current, serialized: state.clean.serialized }),
  });
  toast(`已应用，原文件备份于 ${res.backup.split(/[\\/]/).pop()}`);
  await init();
  selectSkill(state.current);
}

/* ---------- 追踪 ---------- */
async function renderTrack() {
  const st = await api(`/api/tracking/${encodeURIComponent(state.current)}`);
  const rows = Object.entries(st).map(([k, v]) => `<div class="kv"><span class="k">${k}</span><span>${v.count} 次 · 累计节省 ${v.saved} token · 最近 ${esc((v.last||"").slice(0,19).replace("T"," "))}</span></div>`).join("");
  $("#tab-track").innerHTML = `<div class="card"><h3>调用效果追踪 · ${state.current}</h3>${rows || "<div style='color:var(--muted)'>暂无记录，运行清洗/应用后将在此累计。</div>"}</div>`;
}

/* ---------- 看板 ---------- */
async function renderDashboard() {
  const [stats, spec] = await Promise.all([api("/api/stats"), api("/api/spec")]);
  $("#specVer").textContent = spec.standard_version;
  $("#specTpl").textContent = spec.skill_template;
  $("#specRules").innerHTML = spec.rules.map((r) =>
    `<div class="rule"><span class="rc">${esc(r.id)}</span>${r.source==="custom" ? '<span class="src-tag">custom</span>' : ""} [${esc(r.dim)}/${esc(r.severity)}] <b>${esc(r.field)}</b><br>${esc(r.rule)}</div>`
  ).join("");

  const perTurn = stats.per_turn_saving;
  const kpis = [
    ["已优化技能", stats.applied_skills, "个"],
    ["累计节省 Token", stats.total_saved, "t"],
    ["每轮常驻节省", perTurn, "t/轮"],
    ["千轮会话节省", perTurn * 1000, "t"],
  ];
  $("#kpiRow").innerHTML = kpis.map(([l, v]) =>
    `<div class="kpi"><div class="v" data-count="${v}">0</div><div class="l">${l}</div></div>`
  ).join("");

  // 趋势图
  const series = stats.series || [];
  if (!series.length) $("#chartSeries").innerHTML = `<div class="guide-empty" style="padding:28px 14px">
    <div class="ge-emoji">📈</div>
    <div class="ge-title">趋势图还空着</div>
    <div class="ge-text">去 <b>技能资产</b> 页选一个技能 → 进「清洗」→ 点「<b>应用并写回文件</b>」，每次应用都会在这里累积一条按天的节省记录。</div>
  </div>`;
  else {
    const max = Math.max(1, ...series.map((s) => s.saved));
    $("#chartSeries").innerHTML = series.map((s) =>
      `<div class="bar-row"><span class="nm">${esc(s.day)}</span><span class="bar-track"><span class="bar-fill" data-w="${Math.round(s.saved/max*100)}"></span></span><span class="val">${s.saved}t</span></div>`
    ).join("");
  }
  const lb = stats.leaderboard || [];
  if (!lb.length) $("#chartLeader").innerHTML = `<div class="guide-empty" style="padding:28px 14px">
    <div class="ge-emoji">🏆</div>
    <div class="ge-title">排行还空着</div>
    <div class="ge-text">同样需要先到 <b>技能资产</b> 页运行清洗并应用，才会按技能统计节省排行。</div>
  </div>`;
  else {
    const max = Math.max(1, ...lb.map((s) => s.saved));
    $("#chartLeader").innerHTML = lb.map((s) =>
      `<div class="bar-row"><span class="nm">${esc(s.skill_id)}</span><span class="bar-track"><span class="bar-fill" data-w="${Math.round(s.saved/max*100)}"></span></span><span class="val">${s.saved}t</span></div>`
    ).join("");
  }
  countUpAll($(".dash"));
  // bar 宽度过渡（CSS 已对 .bar-fill 做 width 过渡）
  requestAnimationFrame(() => {
    document.querySelectorAll(".dash .bar-fill").forEach((b) => (b.style.width = (b.dataset.w || 0) + "%"));
  });
}

/* ---------- 冲突检测 ---------- */
function renderConflicts() {
  const cfg = { backend: "local-tfidf" };
  $("#conflictsPanel").innerHTML = `
    <div class="card">
      <h3>语义冲突检测 · 跨技能 description 两两相似度</h3>
      <div class="kv"><span class="k">向量后端</span><span>
        <label><input type="radio" name="confBackend" value="local-tfidf" checked> local-tfidf（零依赖）</label>
        <label style="margin-left:10px"><input type="radio" name="confBackend" value="embedding"> embedding-API</label>
      </span></div>
      <div class="slider-row">
        <label>相似度阈值 <b id="thVal">0.70</b></label>
        <input type="range" id="thSlider" min="0.5" max="0.95" step="0.01" value="0.7">
      </div>
      <div class="row"><button class="btn" id="runConfBtn">🔄 重新计算</button>
        <span class="note">阈值越低误报越多，越高漏报越多。</span></div>
    </div>
    <div id="conflictsList"></div>`;
  $("#thSlider").oninput = () => ($("#thVal").textContent = (+$("#thSlider").value).toFixed(2));
  $("#runConfBtn").onclick = loadConflicts;
  loadConflicts();
}

async function loadConflicts() {
  const threshold = +$("#thSlider")?.value || 0.7;
  $("#conflictsList").innerHTML = `<div class="card"><div class="note">计算中…</div></div>`;
  try {
    const r = await api(`/api/conflicts?threshold=${threshold}`);
    if (!r.pairs.length) {
      $("#conflictsList").innerHTML = `<div class="card"><div style="color:var(--green)">✓ 未检测到相似度 ≥ ${threshold} 的冲突技能对。</div></div>`;
      return;
    }
    const cards = r.pairs.map((p, i) => `
      <div class="conflict-card">
        <div class="conf-head"><b>${esc(p.skill_a)}</b> ↔ <b>${esc(p.skill_b)}</b> <span class="badge ${p.similarity>0.85?"invalid":"warning"}">相似度 ${p.similarity}</span></div>
        <div class="sug">重叠关键词：${(p.shared_keywords||[]).map((k)=>`<span class="tag">${esc(k)}</span>`).join("") || "—"}</div>
        <div class="sug">建议：${esc(p.suggestion)}</div>
        <button class="btn secondary" data-deposit="${i}">沉淀为新规则</button>
      </div>`).join("");
    $("#conflictsList").innerHTML = `<div class="card"><h3>潜在冲突技能对（${r.pairs.length}）</h3>${cards}</div>`;
    document.querySelectorAll("#conflictsList .conflict-card").forEach((c, i) => (c.style.animationDelay = (i * 0.06) + "s"));
    document.querySelectorAll("#conflictsList [data-deposit]").forEach((b) =>
      b.onclick = () => depositRule(r.pairs[+b.dataset.deposit])
    );
  } catch (e) {
    $("#conflictsList").innerHTML = `<div class="card" style="color:var(--red)">检测失败：${esc(e.message)}</div>`;
  }
}

async function depositRule(pair) {
  const kc = prompt("沉淀为冲突规则的关键词簇（逗号分隔）：", (pair.shared_keywords || []).join(",") || `${pair.skill_a},${pair.skill_b}`);
  if (kc === null) return;
  const keyword_cluster = kc.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
  try {
    const r = await api("/api/rules/custom", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword_cluster, suggestion: pair.suggestion }),
    });
    toast(`已沉淀规则 ${r.rule.id}（${r.rule.dim}），/api/spec 即时生效`);
  } catch (e) {
    toast("沉淀失败：" + e.message);
  }
}

/* ---------- v2.8 Prompt 简化器（可多选规则 + 保守/激进预设） ---------- */
/* 规则 id 单一真源，必须与后端 skillforge.prompt_simplifier.ALL_RULE_IDS 逐字一致（共 19 类）。 */
const SIMPLIFY_RULE_IDS = [
  "politeness","first_person","courtesy_boilerplate","role_prefix","empty_items","duplicate_lines","blank_lines",
  "meta_comment","hedging","redundant_adverbs","examples_trim",
  "logical_connector","filler_particles",
  "duplicate_clauses","punctuation_compress","punctuation_normalize",
  "condition_clause","redundant_enum","semantic_compress",
];
/* 保守 = 5 基础 + meta_comment + filler_particles + duplicate_clauses +
          punctuation_compress + punctuation_normalize + condition_clause + redundant_enum
          （**不含** logical_connector / first_person 等更深类别，Q2）。
   激进 = 保守全集 ∪ first_person + courtesy_boilerplate + hedging + redundant_adverbs + examples_trim + logical_connector
          （严格 ⊃，共 18 类；仅 semantic_compress 仍 explicit-only 不进预设，Q5）。
   evo2-15：condition_clause / redundant_enum（长文本增强）默认进两档预设，使长啰嗦需求散文
            默认即可压掉「…的话」保留语与「再X/…操作」冗余枚举，解决「只能减少几个字」。
   模式差异落点：前端预设真正分层（aggressive ⊃ balanced + 更深类别），后端 PRESETS 不动（零回归）。
   后端 PRESETS（rules=None）始终保持 v2.5 的 5 基础类，零回归契约不受前端预设影响。 */
const SIMPLIFY_PRESETS = {
  balanced:   { mode: "balanced",   rules: ["politeness","role_prefix","empty_items","duplicate_lines","blank_lines","meta_comment","filler_particles","duplicate_clauses","punctuation_compress","punctuation_normalize","condition_clause","redundant_enum"] },
  aggressive: { mode: "aggressive", rules: ["politeness","role_prefix","empty_items","duplicate_lines","blank_lines","meta_comment","filler_particles","duplicate_clauses","punctuation_compress","punctuation_normalize","condition_clause","redundant_enum","first_person","courtesy_boilerplate","hedging","redundant_adverbs","examples_trim","logical_connector"] },
};

/* ---------- v2.11 规则说明元数据（可枚举展示 19 类，满足用户「全部列出来」） ---------- */
/* 每类：{id, name, group, criteria, remove_examples, keep_examples, explicit_only, in_balanced, in_aggressive}
   - explicit_only：是否仅显式勾选生效（不进后端 PRESETS）；first_person 等显式类为 true。
   - in_balanced / in_aggressive：按 SIMPLIFY_PRESETS（T03 Design A）填。 */
const RULE_META = [
  { id: "politeness", name: "礼貌 / 冗余填充词", group: "基础裁剪",
    criteria: "移除对模型的客套/指令语气冗余短语（您/请/谢谢/你应该/你必须）+ 英文 please/you should 等；显式或激进模式叠加更激进词表（麻烦/劳烦/最好/务必…）并删单字「请」。",
    remove_examples: "「请您」「谢谢」「你好」「请务必」「you should」→ 删；激进下「麻烦」「最好」→ 删。",
    keep_examples: "含「请」的安全词（申请/请求/请教）冻结不删；裸字「请」在保守且不显式时保留。",
    explicit_only: false, in_balanced: true, in_aggressive: true },
  { id: "first_person", name: "第一人称自指冗余", group: "进阶精简",
    criteria: "移除说话人自己的冗余自指标记（分五组）。①受益/对象：给我/为我/替我/由我/同我/向我/对我/帮我。②并列歧义：和我/与我 仅当后接动词（如「和我确认/与我讨论/和对齐」）才删，避免误删「我和张三」并列构式。③视角：依我看/在我看来/我个人认为。④意愿：我想要/我希望/我需要/我打算/我计划/我要求/我期待/我建议/我考虑。⑤客套求助：请帮我/麻烦帮我/劳烦帮我/求你帮我。另「我想」须锚定后接动词才删（避免误删「我想你/我想家」）。全程在否定护栏下，裸字「我/我的」不删。",
    remove_examples: "「请给我写个爬虫」→「请写个爬虫」；「依我看这样更好」→「这样更好」；「我想写一个函数」→「写一个函数」。",
    keep_examples: "「我和张三的日程」「我的账号」等承载区分信息的「我/我的」；「别给我发邮件」否定辖域内的自指标记；英文 me/my 当前未覆盖（P2）。",
    explicit_only: true, in_balanced: false, in_aggressive: true,
    note: "与「礼貌/冗余填充词」存在双重归属：「请帮我/帮我」等客套求助类由 politeness（显式路径）先行移除，本规则随后处理其余第一人称自指标记（给我/依我看/我想…），两者可同开、互不替代。" },
  { id: "courtesy_boilerplate", name: "客套 / 寒暄冗余", group: "进阶精简",
    criteria: "移除无信息量的客套/寒暄噪声（长词优先，避免残留孤立「你」）。①招呼：你好/您好/在吗/嗨。②道歉：对不起/抱歉/不好意思/打扰了。③感谢：谢谢/感谢/辛苦了/麻烦了（含「谢谢你/感谢你」整体删）。④客套求助（条件式）：如果可以的话/如果方便的话。⑤结尾套话：仅供参考/不吝赐教/敬请谅解/如有问题/请知悉。运行顺序置 politeness 之前，使「感谢你」整体移除。",
    remove_examples: "「你好，请给我写个爬虫，谢谢，辛苦了。」→「，请给我写个爬虫，。」；「非常感谢你」→「非常」（感谢你整体删）。",
    keep_examples: "承载指令语义的「请/麻烦/劳烦」（由 politeness 处理）；代码/URL 内文本冻结不删。",
    explicit_only: true, in_balanced: false, in_aggressive: true,
    note: "与 politeness 互补：politeness 负责「请/麻烦/帮我」等指令语气词，本规则只收纯礼貌套话（你好/谢谢/抱歉/辛苦了/仅供参考）。两者可同开、互不替代、不重复计数。" },
  { id: "role_prefix", name: "冗长角色描述", group: "基础裁剪",
    criteria: "行首冗长角色前缀（你是一个专业的助手/我希望你扮演…）精简为「角色：」；激进模式追加行内中文角色前缀兜底移除。",
    remove_examples: "「你是一个专业的 Python 专家」→「角色：Python 专家」。",
    keep_examples: "普通正文中的「你是一个函数」不误删（保守模式行内不删）。",
    explicit_only: false, in_balanced: true, in_aggressive: true },
  { id: "empty_items", name: "空列表项", group: "基础裁剪",
    criteria: "删除行首 - * • + 或 数字./) 或 字母./) 之后无实际内容的空列表项。",
    remove_examples: "「- 」(空) / 「1. 」(空) → 删除整行。",
    keep_examples: "「- 有效内容」保留。",
    explicit_only: false, in_balanced: true, in_aggressive: true },
  { id: "duplicate_lines", name: "重复指令", group: "基础裁剪",
    criteria: "按归一化（去空白/标点/小写）合并逐行重复指令，仅保留首次。",
    remove_examples: "连续两行「步骤：打开。」→ 保留一行。",
    keep_examples: "仅标点/空白不同的两行（低风险）可能保留。",
    explicit_only: false, in_balanced: true, in_aggressive: true },
  { id: "blank_lines", name: "空行折叠", group: "基础裁剪",
    criteria: "折叠连续空行为至多一个，并清理每行首尾空白。",
    remove_examples: "多个连续空行 → 单个空行。",
    keep_examples: "代码块前后的刻意空行经占位符保护后还原。",
    explicit_only: false, in_balanced: true, in_aggressive: true },
  { id: "meta_comment", name: "元评论 / 过渡句", group: "进阶精简",
    criteria: "移除元评论/过渡短语（此外/另外/换句话说/总而言之…）。深化：需要注意的是/值得注意的是/明确地说/具体来说/具体而言仅在句首且后接「，/。」时才删。",
    remove_examples: "「此外，我们需要」→「我们需要」；「需要注意的是，任务很简单。」→「任务很简单。」。",
    keep_examples: "「需要注意的是必须验证」(句首但后接关键内容) 保留；句中「…，需要注意的是…」保留。",
    explicit_only: true, in_balanced: true, in_aggressive: true },
  { id: "hedging", name: "弱语气词", group: "进阶精简",
    criteria: "移除弱语气/不确定性词（可能/也许/大概/或许/估计/难免/基本上…），带否定前瞻避免误伤「不可能」。注意「应该」已移出（指令语境强约束保护）。",
    remove_examples: "「也许他会来」→「他会来」；「估计可行」→「可行」。",
    keep_examples: "「你应该返回 JSON」的「应该」保留（强约束）；「不可能」「并没有完全」否定结构保留。",
    explicit_only: true, in_balanced: false, in_aggressive: true },
  { id: "redundant_adverbs", name: "冗余副词", group: "进阶精简",
    criteria: "移除冗余强调副词（非常/十分/极其/完全/绝对/彻底…），带否定前瞻。深化：后接对比词（不同/相反/独立/新的/差异/区别/区分）时不删。",
    remove_examples: "「非常感谢」→「感谢」；「十分稳定」→「稳定」。",
    keep_examples: "「完全不同的方案」「绝对独立的模块」中区分性用法保留；「不完全」否定结构保留。",
    explicit_only: true, in_balanced: false, in_aggressive: true },
  { id: "examples_trim", name: "过长示例压缩", group: "进阶精简",
    criteria: "示例引导词（例如/比如/示例如下…）后连续块 ≥4 行或 ≥200 字符→压缩为前 3 行 + 标注；受保护片段（代码/URL）原样保留。",
    remove_examples: "「例如：」后 6 行 → 保留前 3 行 + 「（示例已压缩，共 6 行）」。",
    keep_examples: "示例块 <4 行且 <200 字符不压缩；含代码块则全部真实行保留。",
    explicit_only: true, in_balanced: false, in_aggressive: true },
  { id: "logical_connector", name: "逻辑 / 过渡连接词", group: "进阶精简",
    criteria: "移除逻辑/序列/总结/过渡连接词（因此/但是/然后/总之/其实…），带否定前瞻；条件标记（如果/则/否则）永不删；有序/无序列表行内序列词（首先/然后/最后）受保护。",
    remove_examples: "「因此，我们需要启动」→「我们需要启动」。",
    keep_examples: "「如果…则…否则」控制流保留；「- 首先…」步骤提示保留；「不因此」否定结构保留。",
    explicit_only: true, in_balanced: false, in_aggressive: true },
  { id: "filler_particles", name: "句末语气助词", group: "进阶精简",
    criteria: "移除句末语气助词（啊/呢/吧/嘛/呀/哦/啦…），仅句末（后接 。！？ 或文末）且带否定前瞻；「吗」刻意不纳入。",
    remove_examples: "「你帮我看看这个啊。」→「你帮我看看这个。」。",
    keep_examples: "「吗」保留（疑问句意图）；句中「这个呢，那个」不删。",
    explicit_only: true, in_balanced: true, in_aggressive: true },
  { id: "duplicate_clauses", name: "跨句重复子句去重", group: "进阶精简",
    criteria: "跨句完全重复子句去重（整句精确重复 / 长重复前缀），仅显式勾选生效，阈值 4 CJK 字护栏。",
    remove_examples: "「请确保输出 JSON。请确保输出 JSON 并校验字段。」→「请确保输出 JSON。并校验字段。」。",
    keep_examples: "不同文件引用（config.py/output.log）不误删；句末尾词（报告）不删。",
    explicit_only: true, in_balanced: true, in_aggressive: true },
  { id: "punctuation_compress", name: "连续标点折叠", group: "进阶精简",
    criteria: "折叠 3+ 连续 。！？.!? → 单字符；排除 ASCII `.` 以保护省略号 `...`。",
    remove_examples: "「真的吗？？？」→「真的吗？」。",
    keep_examples: "双连标点（！！/？？）保留；……/—— 保留；代码内标点冻结。",
    explicit_only: true, in_balanced: true, in_aggressive: true },
  { id: "punctuation_normalize", name: "标点归一化", group: "进阶精简",
    criteria: "折叠 2+ 连续相同 CJK 标点（，。！？；：、）为单个 + 规整标点周围 ASCII 空格；仅冗余归一化。",
    remove_examples: "「你好 ？？」→「你好？」；「你好 ， 世界」→「你好，世界」。",
    keep_examples: "单标点、引号、括号原样保留；……/—— 保留。",
    explicit_only: true, in_balanced: true, in_aggressive: true },
  { id: "condition_clause", name: "条件 / 保留语境 hedge 剪枝", group: "长文本增强",
    criteria: "删除无信息量的前提/保留语短语（…的话 / 有充足真实依据的话 / 说实话 / 平心而论…），保留主干断言；删除后对残留孤立/连续逗号做最小规整。evo2-15 长文本增强。",
    remove_examples: "「冲突检测真的可以实现的话可以保留」→「冲突检测可以保留」；「数据看板有充足真实依据的话可以保留」→「数据看板可以保留」。",
    keep_examples: "承载指令语义的条件（如果…则…否则）保留；疑问句「吗」相关保留；受保护片段内不触碰。",
    explicit_only: true, in_balanced: true, in_aggressive: true,
    note: "与 courtesy_boilerplate 互补：courtesy 收纯礼貌套话（你好/谢谢/如果方便的话），本规则收更全的 caveat 集合（真的可以实现的话/有充足真实依据的话/说实话…），两者可同开、互不替代。" },
  { id: "redundant_enum", name: "冗余枚举折叠", group: "长文本增强",
    criteria: "针对斜杠分隔枚举：① 末项冗余名词尾（操作/处理/工作/动作…）剥除；② 若某项 = 前缀(再/重新/再次/重/复…) + 同组另一项 → 删较长冗余项。仅作用于 / 分隔短项枚举。evo2-15 长文本增强。",
    remove_examples: "「清洗/还原/再清洗/追踪变更历程操作」→「清洗/还原/追踪变更历程」（删「再清洗」与末项「操作」）。",
    keep_examples: "URL/代码内 / 受保护不触碰；无前缀冗余与尾名词的普通枚举（如 MCP/skill）原样保留。",
    explicit_only: true, in_balanced: true, in_aggressive: true },
  { id: "semantic_compress", name: "语义压缩（本地）", group: "进阶精简",
    criteria: "本地 embedding 近义/重复句折叠（能力1）+ 可选重要性剪枝（能力2）；仅显式勾选 + 需本地 embedding，不可用时静默跳过。",
    remove_examples: "同主题近义句「T1 近义句一。T1 近义句二。」→ 折叠为单句。",
    keep_examples: "含指令/条件/代码/否定的句剪枝时不动；无 embedding 后端则完全跳过。",
    explicit_only: true, in_balanced: false, in_aggressive: false },
];

/* 渲染「规则说明」面板（由 index.html 的 #ruleMetaBody 容器承载） */
function renderRuleMeta() {
  const panel = document.getElementById("ruleMetaBody");
  if (!panel) return;
  panel.innerHTML = RULE_META.map((m) => {
    const tags = [];
    if (m.in_balanced) tags.push('<span class="rm-tag balanced">保守</span>');
    if (m.in_aggressive) tags.push('<span class="rm-tag aggressive">激进</span>');
    if (!m.in_balanced && !m.in_aggressive) tags.push('<span class="rm-tag explicit-only">仅显式</span>');
    else if (m.explicit_only) tags.push('<span class="rm-tag explicit">显式</span>');
    return `<div class="rm-item">
      <div class="rm-head"><b>${esc(m.name)}</b> <code>${esc(m.id)}</code>` +
        `<span class="rm-group">${esc(m.group)}</span> ${tags.join("")}</div>
      <div class="rm-line"><b>筛选标准：</b>${esc(m.criteria)}</div>
      <div class="rm-line"><b>命中示例：</b>${esc(m.remove_examples)}</div>
      <div class="rm-line"><b>保留边界：</b>${esc(m.keep_examples)}</div>` +
      (m.note ? `<div class="rm-note">${esc(m.note)}</div>` : "") +
      `</div>`;
  }).join("");
}

function getSimplifyState() {
  const rules = SIMPLIFY_RULE_IDS.filter((id) => {
    const el = document.querySelector('input[data-rule="' + id + '"]');
    return el && el.checked;
  });
  const active = document.querySelector(".preset.active");
  const mode = active ? (active.dataset.preset === "aggressive" ? "aggressive" : "balanced") : "balanced";
  // v2.9 语义压缩参数：仅当 semantic_compress 勾选时附带（后端仅在含该 id 时生效）
  let semantic_threshold = 0.90;
  let semantic_prune = false;
  const semEl = document.querySelector('input[data-rule="semantic_compress"]');
  if (semEl && semEl.checked) {
    const thEl = document.querySelector("#semThreshold");
    const th = parseFloat((thEl && thEl.value) || "0.90");
    if (!isNaN(th)) semantic_threshold = Math.min(0.98, Math.max(0.80, th));
    const prEl = document.querySelector("#semPrune");
    semantic_prune = !!(prEl && prEl.checked);
  }
  return { rules, mode, semantic_threshold, semantic_prune };
}

function applySimplifyPreset(name) {
  const p = SIMPLIFY_PRESETS[name];
  if (!p) return;
  SIMPLIFY_RULE_IDS.forEach((id) => {
    const el = document.querySelector('input[data-rule="' + id + '"]');
    if (el) el.checked = p.rules.includes(id);
  });
  document.querySelectorAll(".preset").forEach((b) => b.classList.toggle("active", b.dataset.preset === name));
  saveSimplifyState();
}

function saveSimplifyState() {
  try { localStorage.setItem("skillforge_simplify_v2_12", JSON.stringify(getSimplifyState())); } catch (e) {}
}

function loadSimplifyState() {
  try {
    // 优先 v2_12；缺失则迁移 v2_9 / v2_8（用仍存在的 id 过滤后应用并写回 v2_12）
    let raw = localStorage.getItem("skillforge_simplify_v2_12");
    if (!raw) {
      const old = localStorage.getItem("skillforge_simplify_v2_9") || localStorage.getItem("skillforge_simplify_v2_8");
      if (old) {
        try {
          const st = JSON.parse(old);
          if (st && Array.isArray(st.rules)) {
            const migrated = {
              mode: st.mode,
              rules: st.rules.filter((id) => SIMPLIFY_RULE_IDS.includes(id)),
            };
            localStorage.setItem("skillforge_simplify_v2_12", JSON.stringify(migrated));
            raw = JSON.stringify(migrated);
          }
        } catch (e) {}
      }
    }
    if (!raw) return false;
    const st = JSON.parse(raw);
    if (st && Array.isArray(st.rules)) {
      SIMPLIFY_RULE_IDS.forEach((id) => {
        const el = document.querySelector('input[data-rule="' + id + '"]');
        if (el) el.checked = st.rules.includes(id);
      });
      // 恢复 v2.9 语义压缩参数（缺失则回落默认）
      if (st.semantic_threshold != null) {
        const thEl = document.querySelector("#semThreshold");
        if (thEl) thEl.value = String(st.semantic_threshold);
      }
      if (st.semantic_prune) {
        const prEl = document.querySelector("#semPrune");
        if (prEl) prEl.checked = true;
      }
      const cur = getSimplifyState().rules.slice().sort().join(",");
      for (const [name, p] of Object.entries(SIMPLIFY_PRESETS)) {
        if (p.rules.slice().sort().join(",") === cur && p.mode === st.mode) {
          document.querySelectorAll(".preset").forEach((b) => b.classList.toggle("active", b.dataset.preset === name));
          break;
        }
      }
      return true;
    }
  } catch (e) {}
  return false;
}

function initSimplifier() {
  const ta = $("#simplifyInput");
  if (!ta) return;
  // 拖拽 .txt 文件 → 读入 textarea
  ["dragenter", "dragover"].forEach((ev) =>
    ta.addEventListener(ev, (e) => { e.preventDefault(); ta.classList.add("dragging"); })
  );
  ["dragleave", "drop"].forEach((ev) =>
    ta.addEventListener(ev, (e) => { e.preventDefault(); ta.classList.remove("dragging"); })
  );
  ta.addEventListener("drop", (e) => {
    const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".txt")) {
      $("#simplifyErr").textContent = "仅支持 .txt 文件";
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      ta.value = String(reader.result || "");
      $("#simplifyErr").textContent = "";
    };
    reader.readAsText(file);
  });
  // 预设按钮
  document.querySelectorAll(".preset").forEach((b) => {
    b.onclick = () => applySimplifyPreset(b.dataset.preset);
  });
  // 任意勾选变化 → 取消 preset 高亮 + 持久化
  SIMPLIFY_RULE_IDS.forEach((id) => {
    const el = document.querySelector('input[data-rule="' + id + '"]');
    if (el) el.addEventListener("change", () => {
      document.querySelectorAll(".preset").forEach((b) => b.classList.remove("active"));
      saveSimplifyState();
    });
  });
  // v2.9 语义压缩：阈值滑块 + 剪枝开关变化 → 取消 preset 高亮 + 持久化
  const semThresholdEl = document.querySelector("#semThreshold");
  if (semThresholdEl) semThresholdEl.addEventListener("input", () => {
    document.querySelectorAll(".preset").forEach((b) => b.classList.remove("active"));
    saveSimplifyState();
  });
  const semPruneEl = document.querySelector("#semPrune");
  if (semPruneEl) semPruneEl.addEventListener("change", () => {
    document.querySelectorAll(".preset").forEach((b) => b.classList.remove("active"));
    saveSimplifyState();
  });
  // 首次进入：恢复 localStorage，否则默认 保守
  if (!loadSimplifyState()) applySimplifyPreset("balanced");
  renderRuleMeta();   // v2.11：渲染「规则说明」面板（16 类可枚举）
  $("#btnSimplify").onclick = doSimplify;
  $("#btnCopySimplify").onclick = () => {
    navigator.clipboard.writeText($("#simplifyResult").value);
    toast("已复制简化结果到剪贴板");
  };
  $("#btnExportSimplify").onclick = exportSimplify;
}

async function doSimplify() {
  const text = $("#simplifyInput").value;
  if (!text.trim()) {
    $("#simplifyErr").textContent = "请先输入或拖入 prompt 文本";
    return;
  }
  $("#simplifyErr").textContent = "";
  const { rules, mode, semantic_threshold, semantic_prune } = getSimplifyState();
  // 严格执行：未勾选任何规则时不静默原样返回，明确提示用户（避免「点啥都没反应」的错觉）
  if (!rules.length) {
    $("#simplifyErr").textContent = "请至少勾选一条规则，或点击「均衡 / 激进」预设";
    return;
  }
  $("#btnSimplify").disabled = true;
  $("#btnSimplify").textContent = "简化中…";
  try {
    const r = await api("/api/simplify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, mode, rules, semantic_threshold, semantic_prune }),
    });
    $("#simplifyResult").value = r.simplified_text ?? "";
    $("#simOrigTokens").textContent = r.original_tokens ?? 0;
    $("#simSimpTokens").textContent = r.simplified_tokens ?? 0;
    $("#simSavedTokens").textContent = r.tokens_saved ?? 0;
    $("#simSavedPct").textContent = (r.savings_pct ?? 0) + "%";
    const ul = $("#simplifyChanges ul");
    const changes = (r.changes && r.changes.length) ? r.changes : ["无需变更"];
    ul.innerHTML = changes.map((c) => `<li>${esc(c)}</li>`).join("");
  } catch (e) {
    $("#simplifyErr").textContent = "简化失败：" + e.message;
  } finally {
    $("#btnSimplify").disabled = false;
    $("#btnSimplify").textContent = "⚡ 一键简化";
  }
}

function exportSimplify() {
  const txt = $("#simplifyResult").value || "";
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const blob = new Blob([txt], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `simplified_${ts}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast(`已导出 simplified_${ts}.txt`);
}

/* ---------- 导航/标签 ---------- */
function showView(name) {
  const map = {
    simplify: ["#nav-simplify", "#view-simplify"],
    assets: ["#nav-assets", "#view-assets"],
    conflicts: ["#nav-conflicts", "#view-conflicts"],
    dashboard: ["#nav-dashboard", "#view-dashboard"],
    personal: ["#nav-personal", "#view-personal"],
  };
  for (const [n, [btn, view]] of Object.entries(map)) {
    $(btn).classList.toggle("active", n === name);
    $(view).classList.toggle("hidden", n !== name);
  }
  if (name === "conflicts") renderConflicts();
  if (name === "dashboard") renderDashboard();
  if (name === "personal") renderPersonal();
}
function bindNav() {
  $("#nav-simplify").onclick = () => showView("simplify");
  $("#nav-assets").onclick = () => showView("assets");
  $("#nav-conflicts").onclick = () => showView("conflicts");
  $("#nav-dashboard").onclick = () => showView("dashboard");
  $("#nav-personal").onclick = () => showView("personal");
}
function bindTabs() {
  document.querySelectorAll(".tab[data-tab]").forEach((t) => t.onclick = () => switchTab(t.dataset.tab));
}
function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["overview", "validate", "clean", "track"].forEach((n) => $("#tab-" + n).classList.toggle("hidden", n !== name));
  if (name === "clean" && !$("#tab-clean").innerHTML) runClean();
  if (name === "track") renderTrack();
}

/* ---------- 个性化口癖（v2.14 · 用户自定义常写、白费 token 的口癖，简化时默认消除） ---------- */
async function renderPersonal() {
  // 进入视图即绑定添加 / 回车，并刷新清单
  const addBtn = $("#addPhraseBtn");
  if (addBtn) addBtn.onclick = addPhrase;
  const input = $("#phraseInput");
  if (input) input.onkeydown = (e) => { if (e.key === "Enter") addPhrase(); };
  await loadPersonalPhrases();
}

async function loadPersonalPhrases() {
  const list = $("#phraseList");
  if (!list) return;
  list.innerHTML = `<div class="note">加载中…</div>`;
  try {
    const r = await api("/api/personal/phrases");
    renderPhraseList(r.phrases || []);
  } catch (e) {
    list.innerHTML = `<div class="note" style="color:var(--red)">加载失败：${esc(e.message)}</div>`;
  }
}

function renderPhraseList(phrases) {
  const list = $("#phraseList");
  const empty = $("#phraseEmpty");
  if (!list) return;
  if (!phrases.length) {
    list.innerHTML = "";
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";
  list.innerHTML = phrases.map((p) =>
    `<div class="phrase-item">
      <span class="phrase-text">${esc(p)}</span>
      <button class="btn secondary phrase-del" data-phrase="${esc(p)}">删除</button>
    </div>`
  ).join("");
  list.querySelectorAll(".phrase-del").forEach((b) => (b.onclick = () => removePhrase(b.dataset.phrase)));
}

async function addPhrase() {
  const input = $("#phraseInput");
  if (!input) return;
  const phrase = (input.value || "").trim();
  if (!phrase) {
    toast("请先输入一个口癖");
    return;
  }
  try {
    const r = await api("/api/personal/phrases", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phrase }),
    });
    input.value = "";
    renderPhraseList(r.phrases);
    toast(r.added ? `已添加「${phrase}」` : `「${phrase}」已在清单中`);
  } catch (e) {
    toast("添加失败：" + e.message);
  }
}

async function removePhrase(phrase) {
  try {
    const r = await api("/api/personal/phrases", {
      method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phrase }),
    });
    renderPhraseList(r.phrases);
    toast(`已删除「${phrase}」`);
  } catch (e) {
    toast("删除失败：" + e.message);
  }
}

// 先同步绑定 UI 事件（导航、资产详情 Tab），再异步拉数据；即使 init() 失败，Tab 也能点。
bindNav();
bindTabs();
init().catch((e) => { $("#meta").textContent = "初始化失败：" + e.message; });
