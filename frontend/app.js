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

/* ---------- v2.7 Prompt 简化器（可多选规则 + 保守/激进预设） ---------- */
/* 规则 id 单一真源，必须与后端 skillforge.prompt_simplifier.ALL_RULE_IDS 逐字一致。 */
const SIMPLIFY_RULE_IDS = [
  "politeness","role_prefix","empty_items","duplicate_lines","blank_lines",
  "meta_comment","hedging","redundant_adverbs","examples_trim",
  "logical_connector","filler_particles",
];
/* 保守 = 5 基础 + logical_connector + filler_particles + meta_comment（默认更强）
   激进 = 保守 + hedging + redundant_adverbs + examples_trim（全 11 类）。
   新类别（logical_connector / filler_particles）永不进后端 PRESETS。 */
const SIMPLIFY_PRESETS = {
  balanced:   { mode: "balanced",   rules: ["politeness","role_prefix","empty_items","duplicate_lines","blank_lines","meta_comment","logical_connector","filler_particles"] },
  aggressive: { mode: "aggressive", rules: ["politeness","role_prefix","empty_items","duplicate_lines","blank_lines","meta_comment","hedging","redundant_adverbs","examples_trim","logical_connector","filler_particles"] },
};

function getSimplifyState() {
  const rules = SIMPLIFY_RULE_IDS.filter((id) => {
    const el = document.querySelector('input[data-rule="' + id + '"]');
    return el && el.checked;
  });
  const active = document.querySelector(".preset.active");
  const mode = active ? (active.dataset.preset === "aggressive" ? "aggressive" : "balanced") : "balanced";
  return { rules, mode };
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
  try { localStorage.setItem("skillforge_simplify_v2_7", JSON.stringify(getSimplifyState())); } catch (e) {}
}

function loadSimplifyState() {
  try {
    // 优先 v2_7；缺失则迁移 v2_6（用仍存在的 id 过滤后应用并写回 v2_7）
    let raw = localStorage.getItem("skillforge_simplify_v2_7");
    if (!raw) {
      const old = localStorage.getItem("skillforge_simplify_v2_6");
      if (old) {
        try {
          const st = JSON.parse(old);
          if (st && Array.isArray(st.rules)) {
            const migrated = {
              mode: st.mode,
              rules: st.rules.filter((id) => SIMPLIFY_RULE_IDS.includes(id)),
            };
            localStorage.setItem("skillforge_simplify_v2_7", JSON.stringify(migrated));
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
  // 首次进入：恢复 localStorage，否则默认 保守
  if (!loadSimplifyState()) applySimplifyPreset("balanced");
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
  const { rules, mode } = getSimplifyState();
  $("#btnSimplify").disabled = true;
  $("#btnSimplify").textContent = "简化中…";
  try {
    const r = await api("/api/simplify", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, mode, rules }),
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
