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
  if (list.count) selectSkill(list.skills[0].name);
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
  $("#d-score").textContent = sc;
  $("#d-score").style.color = sc >= 90 ? "var(--green)" : sc >= 60 ? "var(--amber)" : "var(--red)";
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
      }</span> · 健康度 ${v.score}/100</span></div>
      <div class="kv"><span class="k">description Token</span><span><b>${d.desc_tokens}</b> （常驻每轮上下文）</span></div>
      <div class="kv"><span class="k">SKILL.md 总 Token</span><span>${d.total_tokens}</span></div>
      <div class="kv"><span class="k">问题数</span><span>${v.error_count} 错误 / ${v.warning_count} 警告 / ${v.info_count} 提示</span></div>
      ${d.parse_error ? `<div class="kv"><span class="k">解析错误</span><span style="color:var(--red)">${esc(d.parse_error)}</span></div>` : ""}
    </div>
    <div class="card">
      <h3>当前 Frontmatter 字段 (${keys.length})</h3>
      ${keys.map((k) => `<div class="kv"><span class="k">${esc(k)}</span><span class="mono">${esc(String(fm[k])).slice(0, 200)}</span></div>`).join("")}
    </div>`;
  $("#tab-overview").innerHTML = html;
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
    `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`
  ).join("");

  // 仿真趋势数据已随调度/成本模拟写入 SQLite（见 /api/sim/trends），此处保留读取以备扩展看板卡片。

  // 趋势图
  const series = stats.series || [];
  if (!series.length) $("#chartSeries").innerHTML = `<div style="color:var(--muted)">尚无优化记录，运行清洗并应用后会累积数据。</div>`;
  else {
    const max = Math.max(1, ...series.map((s) => s.saved));
    $("#chartSeries").innerHTML = series.map((s) =>
      `<div class="bar-row"><span class="nm">${esc(s.day)}</span><span class="bar-track"><span class="bar-fill" style="width:${Math.round(s.saved/max*100)}%"></span></span><span class="val">${s.saved}t</span></div>`
    ).join("");
  }
  const lb = stats.leaderboard || [];
  if (!lb.length) $("#chartLeader").innerHTML = `<div style="color:var(--muted)">暂无数据。</div>`;
  else {
    const max = Math.max(1, ...lb.map((s) => s.saved));
    $("#chartLeader").innerHTML = lb.map((s) =>
      `<div class="bar-row"><span class="nm">${esc(s.skill_id)}</span><span class="bar-track"><span class="bar-fill" style="width:${Math.round(s.saved/max*100)}%"></span></span><span class="val">${s.saved}t</span></div>`
    ).join("");
  }
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

/* ---------- 导航/标签 ---------- */
function showView(name) {
  const map = {
    assets: ["nav-assets", "view-assets"],
    sim: ["nav-sim", "view-sim"],
    conflicts: ["nav-conflicts", "view-conflicts"],
    dashboard: ["nav-dashboard", "view-dashboard"],
  };
  for (const [n, [btn, view]] of Object.entries(map)) {
    $(btn).classList.toggle("active", n === name);
    $(view).classList.toggle("hidden", n !== name);
  }
  if (name === "sim") renderSim();
  if (name === "conflicts") renderConflicts();
  if (name === "dashboard") renderDashboard();
}
function bindNav() {
  $("#nav-assets").onclick = () => showView("assets");
  $("#nav-sim").onclick = () => showView("sim");
  $("#nav-conflicts").onclick = () => showView("conflicts");
  $("#nav-dashboard").onclick = () => showView("dashboard");
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

init().catch((e) => { $("#meta").textContent = "初始化失败：" + e.message; });
