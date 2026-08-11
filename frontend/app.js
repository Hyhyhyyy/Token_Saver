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
  bindNav();
  bindTabs();
  initSimplifier();     // v2.5：绑定简化器拖拽/按钮（一次绑定）
  bindAnomalyClick();   // B-4：事件委托（一次绑定，不阻塞首屏）
  if (list.count) selectSkill(list.skills[0].name);
  // 使用说明：首次进入自动弹（不阻塞首屏渲染）
  initOnboarding();
}

function renderSidebar() {
  $("#skillCount").textContent = state.skills.length;
  const ul = $("#skillList"); ul.innerHTML = "";
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
  const [stats, spec, trends] = await Promise.all([api("/api/stats"), api("/api/spec"), api("/api/sim/trends")]);
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

  // 仿真趋势数据已随调度/成本模拟写入 SQLite（见 /api/sim/trends），此处保留读取以备扩展看板卡片。

  // 趋势图
  const series = stats.series || [];
  if (!series.length) $("#chartSeries").innerHTML = `<div style="color:var(--muted)">尚无优化记录，运行清洗并应用后会累积数据。</div>`;
  else {
    const max = Math.max(1, ...series.map((s) => s.saved));
    $("#chartSeries").innerHTML = series.map((s) =>
      `<div class="bar-row"><span class="nm">${esc(s.day)}</span><span class="bar-track"><span class="bar-fill" data-w="${Math.round(s.saved/max*100)}"></span></span><span class="val">${s.saved}t</span></div>`
    ).join("");
  }
  const lb = stats.leaderboard || [];
  if (!lb.length) $("#chartLeader").innerHTML = `<div style="color:var(--muted)">暂无数据。</div>`;
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

/* ---------- 仿真沙盘 ---------- */
function renderSim() {
  renderSchedulePanel();
  renderCostPanel();
  document.querySelectorAll("#simTabs .tab").forEach((t) =>
    t.onclick = () => {
      const stab = t.dataset.stab;
      document.querySelectorAll("#simTabs .tab").forEach((x) => x.classList.toggle("active", x === t));
      $("#sim-schedule").classList.toggle("hidden", stab !== "schedule");
      $("#sim-cost").classList.toggle("hidden", stab !== "cost");
    }
  );
}

async function renderSchedulePanel() {
  const g = await api("/api/sim/gold");
  const cfg = await api("/api/config/vectorizer");
  $("#sim-schedule").innerHTML = `
    <div class="card">
      <h3>调度反事实模拟 · 量化「压缩是否伤调度」</h3>
      <div class="kv"><span class="k">Gold 样本</span><span>内置 <b>${g.count}</b> 条（query→正确技能）</span></div>
      <div class="kv"><span class="k">打分后端</span><span>
        <label><input type="radio" name="schedBackend" value="local-tfidf" ${cfg.backend!=="embedding"?"checked":""}> local-tfidf（零依赖）</label>
        <label style="margin-left:10px"><input type="radio" name="schedBackend" value="embedding" ${cfg.backend==="embedding"?"checked":""}> embedding-API</label>
      </span></div>
      <div class="row">
        <button class="btn" id="runScheduleBtn">▶ 运行模拟</button>
        <button class="btn secondary" id="importGoldBtn">导入JSON</button>
        <button class="btn secondary" id="exportGoldBtn">导出</button>
        <input type="file" id="goldFile" accept="application/json" class="hidden">
      </div>
      <div class="note">控制变量：前后两次仅 description 版本不同，其余（打分器/gold/技能集）完全一致。模拟为离线估计，非真实调度。</div>
    </div>
    <div id="scheduleResult"></div>`;
  $("#runScheduleBtn").onclick = runScheduleSim;
  $("#exportGoldBtn").onclick = exportGold;
  $("#importGoldBtn").onclick = () => $("#goldFile").click();
  $("#goldFile").onchange = importGold;
}

async function runScheduleSim() {
  const backend = document.querySelector('input[name="schedBackend"]:checked')?.value;
  $("#scheduleResult").innerHTML = `<div class="card"><div class="note">模拟运行中…</div></div>`;
  try {
    const r = await api("/api/sim/schedule", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backend }),
    });
    const accB = Math.round(r.accuracy_before * 100);
    const accA = Math.round(r.accuracy_after * 100);
    const delta = accA - accB;
    const deltaTxt = delta === 0 ? "持平" : (delta > 0 ? `↑ +${delta}pt` : `↓ ${delta}pt`);
    const perRows = r.per_skill.map((p) => `
      <div class="bar-row">
        <span class="nm">${esc(p.skill_id)}</span>
        <span class="mono">${p.hits_before} → ${p.hits_after}</span>
        <span class="badge ${p.status==="regressed"?"invalid":p.status==="improved"?"valid":"warning"}">${p.status==="regressed"?"回归":p.status==="improved"?"提升":"不变"}</span>
      </div>`).join("") || "<div class='note'>无命中过 gold 的技能。</div>";
    const regRows = r.regressed_skills.map((rg) => `
      <div class="conflict-card">
        <b>⚠ 回归技能：${esc(rg.skill_id)}</b>
        <span class="mono">（命中 ${rg.hits_before} → ${rg.hits_after}）</span>
        <div class="sug">${esc(rg.suggestion)}</div>
        <button class="btn secondary" data-recall="${esc(rg.skill_id)}">↩ 回调该技能压缩预算</button>
      </div>`).join("") || "<div class='note'>无回归技能。</div>";
    $("#scheduleResult").innerHTML = `
      <div class="card">
        <h3>整体选对率（控制变量对比）</h3>
        <div class="kpi-row">
          <div class="kpi"><div class="v">${accB}%</div><div class="l">清洗前</div></div>
          <div class="kpi"><div class="v" style="color:var(--green)">${accA}%</div><div class="l">清洗后</div></div>
          <div class="kpi"><div class="v">${deltaTxt}</div><div class="l">变化</div></div>
          <div class="kpi"><div class="v">${r.evaluated_samples}</div><div class="l">评估样本</div></div>
        </div>
        ${r.skipped_samples ? `<div class="note">已跳过 ${r.skipped_samples} 条样本（正确技能不在当前技能集中）。</div>` : ""}
      </div>
      <div class="card"><h3>逐技能命中对比</h3>${perRows}</div>
      <div class="card"><h3>回归技能</h3>${regRows}</div>`;
    document.querySelectorAll("#scheduleResult [data-recall]").forEach((b) =>
      b.onclick = () => recallBudget(b.dataset.recall)
    );
  } catch (e) {
    $("#scheduleResult").innerHTML = `<div class="card" style="color:var(--red)">模拟失败：${esc(e.message)}</div>`;
  }
}

async function recallBudget(skillId) {
  try {
    const r = await api("/api/sim/budget", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_id: skillId }),
    });
    toast(`已回调 ${skillId} 压缩预算 → target=${r.target}`);
  } catch (e) {
    toast("回调失败：" + e.message);
  }
}

async function exportGold() {
  const g = await api("/api/sim/gold");
  const blob = new Blob([JSON.stringify(g.samples, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "gold_samples.json"; a.click();
  URL.revokeObjectURL(a.href);
}

async function importGold(e) {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const samples = JSON.parse(await file.text());
    const r = await api("/api/sim/gold", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ samples }),
    });
    toast(`已导入 ${r.count} 条 gold 样本`);
    renderSchedulePanel();
  } catch (err) {
    toast("导入失败：" + err.message);
  }
}

async function renderCostPanel() {
  const pr = await api("/api/sim/pricing");
  const skills = await api("/api/skills");
  const sumBefore = skills.skills.reduce((a, s) => a + s.desc_tokens, 0);
  const modelOpts = pr.models.map((m) => `<option value="${esc(m.model)}">${esc(m.model)}</option>`).join("");
  $("#sim-cost").innerHTML = `
    <div class="card">
      <h3>成本/延迟仿真 · 把 token 节省折算为金额与延迟</h3>
      <div class="kv"><span class="k">模型</span><span><select id="costModel">${modelOpts}</select>
        <button class="btn secondary" id="editPriceBtn" style="margin-left:8px">编辑定价表</button></span></div>
      <div class="slider-row">
        <label>技能数 <b id="scSkills">20</b></label>
        <input type="range" id="costSkills" min="1" max="200" value="20">
      </div>
      <div class="slider-row">
        <label>对话轮次 <b id="scTurns">1000</b></label>
        <input type="range" id="costTurns" min="1" max="10000" value="1000">
      </div>
      <div class="slider-row">
        <label>常驻 token/轮（前）<b id="scBefore">${sumBefore||1200}</b></label>
        <input type="range" id="costBefore" min="0" max="${Math.max(5000, sumBefore*2)}" value="${sumBefore||1200}">
      </div>
      <div class="slider-row">
        <label>常驻 token/轮（后）<b id="scAfter">${Math.round((sumBefore||1200)*0.4)}</b></label>
        <input type="range" id="costAfter" min="0" max="${Math.max(5000, sumBefore*2)}" value="${Math.round((sumBefore||1200)*0.4)}">
      </div>
      <div class="row"><button class="btn" id="runCostBtn">▶ 运行仿真</button></div>
      <div class="note">${esc(pr.disclaimer || "")}（快照 ${esc(pr.as_of || "")})</div>
    </div>
    <div id="costResult"></div>`;
  const bind = (id, label) => {
    const s = $("#" + id);
    s.oninput = () => ($("#" + label).textContent = s.value);
  };
  bind("costSkills", "scSkills"); bind("costTurns", "scTurns");
  bind("costBefore", "scBefore"); bind("costAfter", "scAfter");
  $("#runCostBtn").onclick = runCostSim;
  $("#editPriceBtn").onclick = editPricing;
}

async function runCostSim() {
  const model = $("#costModel").value;
  const body = {
    model,
    skills_count: +$("#costSkills").value,
    turns: +$("#costTurns").value,
    resident_tokens_before: +$("#costBefore").value,
    resident_tokens_after: +$("#costAfter").value,
  };
  $("#costResult").innerHTML = `<div class="card"><div class="note">仿真运行中…</div></div>`;
  try {
    const r = await api("/api/sim/cost", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const maxC = Math.max(r.cost_before, r.cost_after, 0.0001);
    const wB = Math.round(r.cost_before / maxC * 100);
    const wA = Math.round(r.cost_after / maxC * 100);
    $("#costResult").innerHTML = `
      <div class="card">
        <h3>结果（${esc(model)}）</h3>
        <div class="kv"><span class="k">每轮常驻 token</span><span>前 <b>${r.per_round_resident_before}</b> | 后 <b>${r.per_round_resident_after}</b></span></div>
        <div class="kv"><span class="k">累计 token</span><span>前 <b>${r.cumulative_before.toLocaleString()}</b> | 后 <b>${r.cumulative_after.toLocaleString()}</b></span></div>
        <div class="kv"><span class="k">折算金额</span><span>前 <b>$${r.cost_before.toFixed(4)}</b> | 后 <b>$${r.cost_after.toFixed(4)}</b> → 省 <b style="color:var(--green)">$${r.saved_amount.toFixed(4)}</b></span></div>
        <div class="kv"><span class="k">每轮延迟</span><span>前 <b>${r.latency_per_round_before}ms</b> | 后 <b>${r.latency_per_round_after}ms</b></span></div>
        <div class="kv"><span class="k">累计延迟</span><span>前 <b>${r.latency_cumulative_before}ms</b> | 后 <b>${r.latency_cumulative_after}ms</b> → 省 <b style="color:var(--green)">${r.saved_latency}ms</b></span></div>
        <div class="compare">
          <div class="cmp-box cmp-before"><h4>before $${r.cost_before.toFixed(2)}</h4><span class="bar-fill" style="display:block;width:${wB}%;height:18px;background:var(--red)"></span></div>
          <div class="cmp-box cmp-after"><h4>after $${r.cost_after.toFixed(2)}</h4><span class="bar-fill" style="display:block;width:${wA}%;height:18px;background:var(--green)"></span></div>
        </div>
      </div>`;
  } catch (e) {
    $("#costResult").innerHTML = `<div class="card" style="color:var(--red)">仿真失败：${esc(e.message)}</div>`;
  }
}

async function editPricing() {
  const pr = await api("/api/sim/pricing");
  const txt = prompt("编辑模型定价表（JSON 数组，每条含 model/input_price_per_1k/output_price_per_1k/latency_overhead_ms/latency_per_token_ms/context_window）：",
    JSON.stringify(pr.models, null, 2));
  if (!txt) return;
  try {
    const models = JSON.parse(txt);
    const r = await api("/api/sim/pricing", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ models }),
    });
    toast(`定价表已更新（${r.models.length} 个模型）`);
    renderCostPanel();
  } catch (e) {
    toast("更新失败：" + e.message);
  }
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
/* 规则 id 单一真源，必须与后端 skillforge.prompt_simplifier.ALL_RULE_IDS 逐字一致（共 17 类）。 */
const SIMPLIFY_RULE_IDS = [
  "politeness","first_person","courtesy_boilerplate","role_prefix","empty_items","duplicate_lines","blank_lines",
  "meta_comment","hedging","redundant_adverbs","examples_trim",
  "logical_connector","filler_particles",
  "duplicate_clauses","punctuation_compress","punctuation_normalize","semantic_compress",
];
/* 保守 = 5 基础 + meta_comment + filler_particles + duplicate_clauses +
          punctuation_compress + punctuation_normalize（**不含** logical_connector，Q2）。
   激进 = 保守全集 ∪ first_person + courtesy_boilerplate + hedging + redundant_adverbs + examples_trim + logical_connector
          （严格 ⊃，共 16 类；仅 semantic_compress 仍 explicit-only 不进预设，Q5）。
   模式差异落点：前端预设真正分层（aggressive ⊃ balanced + 更深类别），后端 PRESETS 不动（零回归）。
   后端 PRESETS（rules=None）始终保持 v2.5 的 5 基础类，零回归契约不受前端预设影响。 */
const SIMPLIFY_PRESETS = {
  balanced:   { mode: "balanced",   rules: ["politeness","role_prefix","empty_items","duplicate_lines","blank_lines","meta_comment","filler_particles","duplicate_clauses","punctuation_compress","punctuation_normalize"] },
  aggressive: { mode: "aggressive", rules: ["politeness","role_prefix","empty_items","duplicate_lines","blank_lines","meta_comment","filler_particles","duplicate_clauses","punctuation_compress","punctuation_normalize","first_person","courtesy_boilerplate","hedging","redundant_adverbs","examples_trim","logical_connector"] },
};

/* ---------- v2.11 规则说明元数据（可枚举展示 16 类，满足用户「全部列出来」） ---------- */
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
    $("#simplifyOutput").classList.remove("hidden");
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
    simplify: ["nav-simplify", "view-simplify"],
    assets: ["nav-assets", "view-assets"],
    sim: ["nav-sim", "view-sim"],
    conflicts: ["nav-conflicts", "view-conflicts"],
    dashboard: ["nav-dashboard", "view-dashboard"],
    evolve: ["nav-evolve", "view-evolve"],
  };
  for (const [n, [btn, view]] of Object.entries(map)) {
    $(btn).classList.toggle("active", n === name);
    $(view).classList.toggle("hidden", n !== name);
  }
  // B-3：离开进化视图时清理倒计时 interval，避免泄漏
  if (name !== "evolve" && _autoTimer) {
    clearInterval(_autoTimer);
    _autoTimer = null;
  }
  if (name === "sim") renderSim();
  if (name === "conflicts") renderConflicts();
  if (name === "dashboard") renderDashboard();
  if (name === "evolve") renderEvolve();
}
function bindNav() {
  $("#nav-simplify").onclick = () => showView("simplify");
  $("#nav-assets").onclick = () => showView("assets");
  $("#nav-sim").onclick = () => showView("sim");
  $("#nav-conflicts").onclick = () => showView("conflicts");
  $("#nav-dashboard").onclick = () => showView("dashboard");
  $("#nav-evolve").onclick = () => showView("evolve");
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

/* ---------- 进化看板（v2.1 + v2.2 + v2.3 · 自主进化引擎 + 进化账本 + 趋势 + 自动循环） ---------- */
function renderEvolve() {
  bindEvolveNav();
  loadLedger();
  loadTrends();
  getAutoStatus();
  loadBackendSource();
  loadPressure();   // A-4：拉取并渲染「上次外部变化」
}

function bindEvolveNav() {
  $("#evolveBootstrapBtn").onclick = bootstrapGold;
  $("#evolveRunBtn").onclick = runEvolve;
  $("#evolveReportBtn").onclick = exportReport;
  $("#evolveCalibrateBtn").onclick = loadCalibration;
  $("#evolveAutoBtn").onclick = toggleAutoEvolve;
  $("#backendProbeBtn").onclick = probeBackend;
  $("#ledgerLimit").onchange = loadLedger;
  $("#ledgerType").onchange = loadLedger;
  $("#ledgerWindow").onchange = loadLedger;
}

/* D-2 后端来源显示：读 GET /api/config/vectorizer 的 backend_source / ollama_available */
async function loadBackendSource() {
  try {
    const cfg = await api("/api/config/vectorizer");
    const el = $("#backendSource");
    if (!el) return;
    const src = cfg.backend_source;
    let label;
    if (src === "local-st") {
      label = `当前后端：local-st（ollama ${cfg.ollama_available ? "可用" : "未探测到"}）`;
    } else if (src === "openai") {
      label = "当前后端：openai";
    } else {
      label = "当前后端：local-tfidf（已回退）";
    }
    el.textContent = label;
    el.className = "backend-source " + (src === "local-tfidf" ? "fallback" : "active");
  } catch (e) { /* 静默：端点可能暂不可用 */ }
}

/* D-2 显式刷新：POST /api/config/vectorizer/probe 重新探测并刷新来源显示 */
async function probeBackend() {
  try {
    await api("/api/config/vectorizer/probe", { method: "POST" });
    await loadBackendSource();
    toast("已重新探测后端可用性");
  } catch (e) {
    toast("探测失败：" + e.message);
  }
}

async function loadLedger() {
  const limit = +($("#ledgerLimit")?.value || 50);
  const type = $("#ledgerType")?.value || "";
  const window = $("#ledgerWindow")?.value || "";
  const bounds = _windowBounds(window);
  let url = `/api/evolve/ledger?limit=${limit}`;
  if (type) url += `&action_type=${encodeURIComponent(type)}`;
  if (bounds.since) url += `&since=${encodeURIComponent(bounds.since)}`;
  if (bounds.until) url += `&until=${encodeURIComponent(bounds.until)}`;
  $("#ledger-timeline").innerHTML = `<div class="note">加载账本…</div>`;
  try {
    const r = await api(url);
    renderTrendCards();
    if (!r.entries.length) {
      $("#ledger-timeline").innerHTML = `<div class="card"><div class="note">暂无进化记录。运行「🌱 播种」或「▶ 运行自主进化」开始积累。</div></div>`;
      return;
    }
    const badgeClass = {
      gold_seed: "valid", budget_auto_recall: "warning",
      budget_manual_override: "warning", conflict_rule_deposit: "invalid",
      calibration: "info", skill_signature_change: "info",
    };
    const rows = r.entries.map((e) => {
      const cls = badgeClass[e.action_type] || "info";
      return `<div class="ledger-row">
        <span class="ledger-badge badge ${cls}">${esc(e.action_type)}</span>
        <span class="ledger-obj mono">${esc(e.object || "—")}</span>
        <span class="ledger-vals mono">${esc(e.before_val || "∅")} → ${esc(e.after_val || "∅")}</span>
        <span class="ledger-trigger tag">${esc(e.trigger)}</span>
        <span class="ledger-ts">${esc((e.ts || "").slice(0, 19).replace("T", " "))}</span>
        <span class="ledger-note">${esc(e.note || "")}</span>
      </div>`;
    }).join("");
    $("#ledger-timeline").innerHTML = `<div class="card"><h3>账本时间线（${r.count}）</h3>${rows}</div>`;
  } catch (e) {
    $("#ledger-timeline").innerHTML = `<div class="card" style="color:var(--red)">加载失败：${esc(e.message)}</div>`;
  }
}

/* 时间窗 -> ISO 边界（UTC，字典序可比）。today=当日 00:00Z 起；week=近 7 天起。 */
function _windowBounds(window) {
  if (!window) return { since: "", until: "" };
  const now = new Date();
  if (window === "today") {
    const start = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 0, 0));
    return { since: start.toISOString(), until: "" };
  }
  if (window === "week") {
    const start = new Date(now.getTime() - 7 * 24 * 3600 * 1000);
    return { since: start.toISOString(), until: "" };
  }
  return { since: "", until: "" };
}

async function bootstrapGold() {
  const force = window.confirm("强制重新播种缺失技能？（取消 = 仅在 gold 不足阈值时播种）");
  try {
    const r = await api("/api/evolve/bootstrap-gold", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force }),
    });
    toast(`已播种 ${r.seeded} 个技能 gold 样本（共 ${r.total} 条）`);
    loadLedger();
  } catch (e) {
    toast("播种失败：" + e.message);
  }
}

async function runEvolve() {
  $("#ledger-timeline").innerHTML = `<div class="note">自主进化运行中…</div>`;
  try {
    const r = await api("/api/evolve/run", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
    });
    toast(`进化完成：播种 ${r.gold.seeded} · 自动回调 ${r.auto_recalled.length} · 沉淀规则 ${r.deposited_rules.length}`);
    renderTrendCards();
    loadLedger();
  } catch (e) {
    toast("进化失败：" + e.message);
  }
}

async function loadCalibration() {
  const limit = +($("#calibLimit")?.value || 30);
  $("#calibration-panel").innerHTML = `<div class="note">校准中…</div>`;
  try {
    const r = await api(`/api/evolve/calibration?limit=${limit}`);
    if (!r.available) {
      // 未启用 embedding：提示而非报错
      $("#calibration-panel").innerHTML = `<div class="note">未启用：当前未配置 embedding 后端（${esc(r.reason || "")}）。仅使用 local-tfidf 打分，无需校准。</div>`;
      return;
    }
    const pairs = (r.top_divergent_pairs || []).map((p) =>
      `<div class="kv"><span class="k">${esc(p.skill_a)} ↔ ${esc(p.skill_b)}</span><span class="mono">local ${p.sim_local} / emb ${p.sim_emb} · 差 ${p.diff}</span></div>`
    ).join("");
    $("#calibration-panel").innerHTML = `
      <div class="kv"><span class="k">可用性</span><span><b style="color:var(--green)">已启用</b> · 采样 ${r.sample_pairs} 对</span></div>
      <div class="kv"><span class="k">Pearson 相关性</span><span class="mono">${r.correlation ?? "N/A"}</span></div>
      <div class="kv"><span class="k">排序分歧</span><span class="mono">${r.rank_divergence ?? "N/A"}</span></div>
      <div class="card" style="margin-top:8px"><h3>分歧最大的技能对</h3>${pairs || "<div class='note'>无</div>"}</div>`;
  } catch (e) {
    $("#calibration-panel").innerHTML = `<div class="note" style="color:var(--red)">校准失败：${esc(e.message)}</div>`;
  }
}

async function exportReport() {
  try {
    const resp = await fetch("/api/evolve/report?format=markdown");
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const text = await resp.text();
    const blob = new Blob([text], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "evolution_report.md";
    a.click();
    URL.revokeObjectURL(a.href);
    toast("已导出 evolution_report.md");
  } catch (e) {
    toast("导出失败：" + e.message);
  }
}

/* ---------- 进化趋势图（C-1 / C-4 · 手写 SVG 折线，零构建零依赖） ---------- */
async function loadTrends() {
  try {
    const r = await api("/api/evolve/trends?limit=100");
    renderTrendChart(r.points || []);
  } catch (e) { /* 静默：不影响账本渲染 */ }
}

/* 手写 SVG 折线渲染：gold 覆盖度（0~100%）+ F1 前(虚)/后(实)。
   空数据占位；每个数据点带 <title> hover tooltip（C-4）。沿用 .trend-svg 视觉。
   B-1：单点/两点画水平参考线 +「样本不足」提示；B-2：相邻点异常高亮 + 「存在 N 处异常」。 */
// 异常阈值（B-2，与后端 config.ANOMALY_F1_DROP / ANOMALY_COV_DROP 对齐，前端可微调）
const ANOMALY_F1_DROP = 0.1;   // f1_acc_after 降幅
const ANOMALY_COV_DROP = 5;    // gold_coverage 下降百分点

function renderTrendChart(points) {
  const emptyGold = `<div class="trend-empty">暂无趋势数据，运行「▶ 运行自主进化」后此处显示 Gold 覆盖度趋势。</div>`;
  const emptyF1 = `<div class="trend-empty">暂无趋势数据。</div>`;
  if (!points || !points.length) {
    $("#trendGold").innerHTML = emptyGold;
    $("#trendF1").innerHTML = emptyF1;
    return;
  }
  _drawTrend("#trendGold", points, {
    label: "Gold 覆盖度 (%)",
    metricLabel: "Gold 覆盖度(%)",
    minY: 0, maxY: 100, value: (p) => p.gold_coverage,
    cls: "trend-line-gold", yFmt: (v) => v.toFixed(1) + "%",
  });
  _drawTrend("#trendF1", points, {
    label: "F1 选对率（清洗前/后）",
    metricLabel: "F1 选对率(后)",
    minY: 0, maxY: 1, dual: true,
    before: (p) => p.f1_acc_before, after: (p) => p.f1_acc_after,
    clsBefore: "trend-line-f1 before", clsAfter: "trend-line-f1 after",
    yFmt: (v) => (v * 100).toFixed(1) + "%",
  });
}

function _drawTrend(sel, points, opt) {
  const W = 560, H = 170, padL = 42, padR = 14, padT = 14, padB = 28;
  const innerW = W - padL - padR, innerH = H - padT - padB;
  const n = points.length;
  const xAt = (i) => padL + (n <= 1 ? 0 : innerW * i / (n - 1));
  const yAt = (v) => padT + innerH * (1 - (v - opt.minY) / ((opt.maxY - opt.minY) || 1));
  const mkPath = (vals) =>
    vals.map((v, i) => `${i ? "L" : "M"}${xAt(i).toFixed(1)} ${yAt(v).toFixed(1)}`).join(" ");

  // B-1：单点（<2）画水平参考线 +「样本不足」提示（==0 已在 renderTrendChart 处理为空占位）
  if (n < 2) {
    const v = (n === 1)
      ? (opt.dual ? opt.after(points[0]) : opt.value(points[0]))
      : (opt.minY + opt.maxY) / 2;
    const y = yAt(v);
    $(sel).innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="trend-svg" preserveAspectRatio="xMidYMid meet">
      <line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" class="trend-ref-line"/>
      <circle cx="${padL}" cy="${y.toFixed(1)}" r="3" class="trend-dot gold"><title>${esc(points[0]?.ts || "")} · ${esc(opt.label)}: ${opt.yFmt(v)}</title></circle>
      <text x="${padL}" y="${(padT + 12).toFixed(1)}" class="trend-insufficient">样本不足，建议运行进化</text>
      <text x="${padL}" y="${H - 6}" class="trend-axis">${esc(opt.label)}</text>
    </svg>`;
    return;
  }

  let grid = "";
  for (let k = 0; k <= 4; k++) {
    const yy = padT + innerH * k / 4;
    const val = opt.maxY - (opt.maxY - opt.minY) * k / 4;
    grid += `<line x1="${padL}" y1="${yy.toFixed(1)}" x2="${W - padR}" y2="${yy.toFixed(1)}" class="trend-grid"/>`;
    grid += `<text x="${padL - 6}" y="${(yy + 3).toFixed(1)}" class="trend-axis" text-anchor="end">${opt.yFmt(val)}</text>`;
  }

  // B-2：相邻点异常比较（gold 覆盖度下降 / F1 后选对率暴跌）
  const anomalies = [];
  for (let i = 1; i < n; i++) {
    if (opt.dual) {
      const prev = opt.after(points[i - 1]), cur = opt.after(points[i]);
      if (prev - cur >= ANOMALY_F1_DROP) {
        anomalies.push({ i, reason: `F1 后选对率下降 ${((prev - cur) * 100).toFixed(1)}pt` });
      }
    } else {
      const prev = opt.value(points[i - 1]), cur = opt.value(points[i]);
      if (prev - cur >= ANOMALY_COV_DROP) {
        anomalies.push({ i, reason: `覆盖度下降 ${(prev - cur).toFixed(1)}pt` });
      }
    }
  }
  const isAnomAt = (i) => anomalies.find((a) => a.i === i);

  let lines = "", dots = "";
  if (opt.dual) {
    const bv = points.map((p) => opt.before(p));
    const av = points.map((p) => opt.after(p));
    lines += `<path d="${mkPath(bv)}" class="${opt.clsBefore}" />`;
    lines += `<path d="${mkPath(av)}" class="${opt.clsAfter}" />`;
    points.forEach((p, i) => {
      const ab = isAnomAt(i);
      const clsB = ab ? "trend-dot before trend-anomaly" : "trend-dot before";
      const clsA = ab ? "trend-dot after trend-anomaly" : "trend-dot after";
      let attrA = `cx="${xAt(i).toFixed(1)}" cy="${yAt(av[i]).toFixed(1)}" r="${ab ? 4.5 : 3}" class="${clsA}"`;
      if (ab) {
        // B-4：异常点补 data-*（前/本值 + 指标 + 序号 + ts），供点击下钻浮层
        const prevV = i > 0 ? av[i - 1] : av[i];
        attrA += ` data-metric="${esc(opt.metricLabel || opt.label)}" data-idx="${i}"` +
                 ` data-prev="${prevV.toFixed(4)}" data-cur="${av[i].toFixed(4)}" data-ts="${esc(p.ts)}"`;
      }
      dots += `<circle ${attrA}><title>${esc(p.ts)} · 后: ${opt.yFmt(av[i])}${ab ? " · ⚠ " + esc(ab.reason) : ""}</title></circle>`;
      dots += `<circle cx="${xAt(i).toFixed(1)}" cy="${yAt(bv[i]).toFixed(1)}" r="3" class="${clsB}"><title>${esc(p.ts)} · 前: ${opt.yFmt(bv[i])}</title></circle>`;
    });
  } else {
    const vv = points.map((p) => opt.value(p));
    lines += `<path d="${mkPath(vv)}" class="${opt.cls}" />`;
    points.forEach((p, i) => {
      const ab = isAnomAt(i);
      const cls = ab ? "trend-dot gold trend-anomaly" : "trend-dot gold";
      let attr = `cx="${xAt(i).toFixed(1)}" cy="${yAt(vv[i]).toFixed(1)}" r="${ab ? 4.5 : 3}" class="${cls}"`;
      if (ab) {
        // B-4：异常点补 data-*（前/本值 + 指标 + 序号 + ts），供点击下钻浮层
        const prevV = i > 0 ? vv[i - 1] : vv[i];
        attr += ` data-metric="${esc(opt.metricLabel || opt.label)}" data-idx="${i}"` +
                ` data-prev="${prevV.toFixed(4)}" data-cur="${vv[i].toFixed(4)}" data-ts="${esc(p.ts)}"`;
      }
      dots += `<circle ${attr}><title>${esc(p.ts)} · ${esc(opt.label)}: ${opt.yFmt(vv[i])}${ab ? " · ⚠ " + esc(ab.reason) : ""}</title></circle>`;
    });
  }

  // B-2 图例：存在 N 处异常
  const legend = anomalies.length
    ? `<text x="${W - padR}" y="${(padT + 12).toFixed(1)}" text-anchor="end" class="trend-anomaly">存在 ${anomalies.length} 处异常</text>`
    : "";

  $(sel).innerHTML = `<svg viewBox="0 0 ${W} ${H}" class="trend-svg" preserveAspectRatio="xMidYMid meet">
    ${grid}${lines}${dots}${legend}
    <text x="${padL}" y="${H - 6}" class="trend-axis">${esc(opt.label)}</text>
  </svg>`;
}

/* ---------- 自动循环状态（B-2 / B-3 · 实时倒计时） ---------- */
let _autoTimer = null;       // setInterval 句柄（切换视图时清理）
let _autoNextSec = null;     // 下次运行剩余秒数

function _fmtCountdown(sec) {
  if (sec == null) return "";
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function _tickAutoStatus() {
  const badge = $("#autoStatus");
  if (!badge) return;
  if (_autoNextSec == null || !badge.classList.contains("on")) return;
  _autoNextSec = Math.max(0, _autoNextSec - 1);
  const last = badge.dataset.last || "";
  badge.textContent = `● 自动进化：运行中${last} · 下次运行 ${_fmtCountdown(_autoNextSec)}`;
}

async function getAutoStatus() {
  // B-3：清理旧 timer（切换视图/重复调用），避免泄漏
  if (_autoTimer) { clearInterval(_autoTimer); _autoTimer = null; }
  try {
    const s = await api("/api/evolve/auto/status");
    const badge = $("#autoStatus");
    if (s.running) {
      badge.className = "auto-badge on";
      _autoNextSec = (s.next_run_in_sec != null) ? s.next_run_in_sec : null;
      const next = _autoNextSec != null ? ` · 下次运行 ${_fmtCountdown(_autoNextSec)}` : "";
      const last = s.last_run ? ` · 上次 ${s.last_run.slice(0, 19).replace("T", " ")}` : "";
      badge.dataset.last = last;
      badge.textContent = `● 自动进化：运行中${last}${next}`;
      $("#evolveAutoBtn").textContent = "⚙ 自动进化：关";
      _autoTimer = setInterval(_tickAutoStatus, 1000);
    } else {
      badge.className = "auto-badge off";
      badge.textContent = "○ 自动进化：暂停";
      _autoNextSec = null;
      $("#evolveAutoBtn").textContent = "⚙ 自动进化：开";
    }
  } catch (e) { /* 静默：端点可能暂不可用 */ }
}

async function toggleAutoEvolve() {
  try {
    const s = await api("/api/evolve/auto/status");
    if (s.running) {
      await api("/api/evolve/auto/stop", { method: "POST" });
      toast("已关闭自动进化循环");
    } else {
      await api("/api/evolve/auto/start", { method: "POST" });
      toast("已开启自动进化循环");
    }
    getAutoStatus();
  } catch (e) {
    toast("切换失败：" + e.message);
  }
}

/* P1-4 看板趋势卡：累计动作 / 自动回调技能数 / 沉淀规则数 / 最近进化时间 */
async function renderTrendCards() {
  try {
    const r = await api("/api/evolve/report?format=json");
    const s = r.summary || { total: 0, by_action_type: {} };
    const autoRecall = s.by_action_type["budget_auto_recall"] || 0;
    const deposited = s.by_action_type["conflict_rule_deposit"] || 0;
    const lastTs = (r.entries && r.entries[0] && r.entries[0].ts)
      ? r.entries[0].ts.slice(0, 19).replace("T", " ") : "—";
    const kpis = [
      { l: "累计自进化动作", v: s.total, u: "次", num: true },
      { l: "自动回调技能", v: autoRecall, u: "次", num: true },
      { l: "沉淀规则", v: deposited, u: "条", num: true },
      { l: "最近进化时间", v: lastTs, u: "", num: false },
    ];
    $("#evolveKpiRow").innerHTML = kpis.map((k) =>
      `<div class="kpi"><div class="v">${k.num ? `<span data-count="${k.v}">0</span>` : esc(k.v)}</div>` +
      `<div class="l">${esc(k.l)}${k.u ? " (" + k.u + ")" : ""}</div></div>`
    ).join("");
    if (s.total) countUpAll($("#evolveKpiRow"));
  } catch (e) { /* 静默：不影响账本渲染 */ }
}

/* ---------- 使用说明（P0 · 首次自动弹 / 顶栏唤起 / localStorage 持久化） ---------- */
function initOnboarding() {
  const KEY = "skillforge_onboarding_v2_4";
  const modal = $("#onboardingModal");
  if (!modal) return;

  const show = () => modal.classList.remove("hidden");
  const hide = () => modal.classList.add("hidden");
  const close = () => {
    // 置位 localStorage → 刷新不再自动弹；多视图再次唤起仍可关闭
    try { localStorage.setItem(KEY, "seen"); } catch (e) { /* 隐私模式忽略 */ }
    hide();
  };

  // 关闭入口：遮罩点击 / X / 「开始使用」按钮
  modal.querySelectorAll("[data-close]").forEach((b) => { b.onclick = close; });
  const startBtn = $("#onboardingStartBtn");
  if (startBtn) startBtn.onclick = close;

  // 顶栏「❓ 使用说明」随时唤起同一模态
  const helpBtn = $("#nav-help");
  if (helpBtn) helpBtn.onclick = show;

  // Esc 关闭（仅模态可见时）
  if (!initOnboarding._escBound) {
    initOnboarding._escBound = true;
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.classList.contains("hidden")) close();
    });
  }

  // 首次（localStorage 未置位）自动弹
  let seen = false;
  try { seen = localStorage.getItem(KEY) === "seen"; } catch (e) { seen = false; }
  if (!seen) show();
}

/* ---------- A-4 压力源可观测：上次外部变化 ---------- */
async function loadPressure() {
  const el = $("#lastExternalChange");
  if (!el) return;
  try {
    const r = await api("/api/evolve/pressure");
    const lc = r.last_change;
    if (lc) {
      const ts = (lc.ts || "").slice(0, 19).replace("T", " ");
      const add = (lc.added || []).length;
      const rem = (lc.removed || []).length;
      const chg = (lc.changed || []).length;
      el.textContent = `★ 上次外部变化：(+${add}新增 / -${rem}删除 / ~${chg}修改) @ ${ts}`;
    } else {
      el.textContent = "★ 上次外部变化：暂无外部变化";
    }
  } catch (e) {
    el.textContent = "★ 上次外部变化：加载失败";
  }
}

/* ---------- B-4 异常详情下钻：点击趋势图异常点浮层 + 定位账本 ---------- */
function bindAnomalyClick() {
  if (bindAnomalyClick._bound) return;  // 仅绑定一次（事件委托）
  bindAnomalyClick._bound = true;
  document.addEventListener("click", (e) => {
    const dot = e.target.closest && e.target.closest(".trend-anomaly");
    if (!dot || !dot.dataset.ts) return;

    const metric = dot.dataset.metric || "指标";
    const prev = parseFloat(dot.dataset.prev);
    const cur = parseFloat(dot.dataset.cur);
    const ts = dot.dataset.ts || "";
    const diff = cur - prev;
    // 变化幅度：绝对差 + 百分比（前值为 0 且变化非 0 记 ∞%）
    let pctTxt;
    if (prev === 0) {
      pctTxt = diff === 0 ? "0%" : "∞%";
    } else {
      pctTxt = ((diff / Math.abs(prev)) * 100).toFixed(1) + "%";
    }
    const sign = diff >= 0 ? "+" : "";

    const panel = $("#anomalyDetail");
    if (!panel) return;
    panel.innerHTML = `
      <div class="anomaly-detail-head">
        <strong>异常详情</strong>
        <button class="anomaly-close" type="button" data-anom-close aria-label="关闭">×</button>
      </div>
      <div class="anomaly-row"><span>指标</span><b>${esc(metric)}</b></div>
      <div class="anomaly-row"><span>前一点</span><b>${prev.toFixed(4)}</b></div>
      <div class="anomaly-row"><span>本点</span><b>${cur.toFixed(4)}</b></div>
      <div class="anomaly-row"><span>变化幅度</span><b class="${diff < 0 ? "down" : ""}">${sign}${diff.toFixed(4)} (${sign}${pctTxt})</b></div>
      <button class="btn secondary" id="anomalyLocateBtn" type="button">定位账本条目</button>
    `;
    panel.classList.remove("hidden");

    panel.querySelector("[data-anom-close]").onclick = () => panel.classList.add("hidden");
    // 点击浮层外部（遮罩区）关闭
    panel.onclick = (ev) => { if (ev.target === panel) panel.classList.add("hidden"); };

    $("#anomalyLocateBtn").onclick = () => {
      // U5：按 data-ts 前 19 字符（YYYY-MM-DD HH:MM:SS）匹配 ledger-row 的 ts 高亮对应行；多行同秒取首个
      const target = ts.slice(0, 19).replace("T", " ");
      const rows = document.querySelectorAll("#ledger-timeline .ledger-row");
      let firstMatch = null;
      rows.forEach((row) => {
        const tsEl = row.querySelector(".ledger-ts");
        const rowTs = tsEl ? (tsEl.textContent || "").trim() : "";
        const match = rowTs.slice(0, 19) === target;
        row.classList.toggle("anomaly-highlight", match);
        if (match && !firstMatch) firstMatch = row;
      });
      if (firstMatch) firstMatch.scrollIntoView({ behavior: "smooth", block: "center" });
    };
  });
}

init().catch((e) => { $("#meta").textContent = "初始化失败：" + e.message; });
