/* SkillForge v2.3 前端趋势图 · 独立真实验证（B-1/B-2）。
 *
 * 直接抽取 frontend/app.js 中 renderTrendChart / _drawTrend 的真实代码，
 * 用最小 DOM 桩（$ / esc）执行，断言 SVG 输出含：
 *   - B-1：<2 点 → 水平参考线(trend-ref-line) + 「样本不足」提示
 *   - B-2：相邻点异常 → 告警色描点(trend-anomaly) + 「存在 N 处异常」图例
 * 零新增依赖（仅 Node 内置 fs）。
 */
const fs = require("fs");
const path = require("path");

const appJs = fs.readFileSync(
  path.join(__dirname, "frontend", "app.js"),
  "utf-8"
);

// 抽取真实渲染代码：从 "const ANOMALY_F1_DROP" 到 _drawTrend 结束后的注释
const startIdx = appJs.indexOf("const ANOMALY_F1_DROP");
const endIdx = appJs.indexOf("/* ---------- 自动循环状态");
if (startIdx < 0 || endIdx < 0) {
  console.error("FAIL: 无法在 app.js 中定位渲染函数");
  process.exit(1);
}
const chunk = appJs.slice(startIdx, endIdx);

// 最小桩：DOM 存储 + esc 转义
const harness = `
const STORE = {};
function $(sel){ return { set innerHTML(v){ STORE[sel] = v; } }; }
function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
}
${chunk}

__exports.renderTrendChart = renderTrendChart;
__exports.clearStore = function(){ for (const k in STORE) delete STORE[k]; };
__exports.STORE = STORE;
`;

const __exports = {};
// 在独立作用域内 eval，使 const/fun 同作用域可见
const runner = new Function("__exports", harness);
runner(__exports);

const renderTrendChart = __exports.renderTrendChart;
const clearStore = __exports.clearStore;
const STORE = __exports.STORE;

// ---- 断言 ----
let failed = 0;
function check(name, cond, detail) {
  console.log(`[${cond ? "PASS" : "FAIL"}] ${name}` + (detail ? ` -- ${detail}` : ""));
  if (!cond) failed++;
}

// B-1：单点 → 参考线 + 样本不足
clearStore();
renderTrendChart([{ ts: "t1", gold_coverage: 100, f1_acc_before: 0.8, f1_acc_after: 0.85 }]);
const gold1 = STORE["#trendGold"] || "";
check("B-1 单点绘制水平参考线(trend-ref-line)", gold1.includes("trend-ref-line"), "");
check("B-1 单点显示「样本不足」提示", gold1.includes("样本不足"), "");

// B-1：两点且平稳 → 无参考线、无异常
clearStore();
renderTrendChart([
  { ts: "t1", gold_coverage: 90, f1_acc_before: 0.8, f1_acc_after: 0.85 },
  { ts: "t2", gold_coverage: 88, f1_acc_before: 0.8, f1_acc_after: 0.85 },
]);
const gold2 = STORE["#trendGold"] || "";
check("B-1 >=2 点不画参考线", !gold2.includes("trend-ref-line"), "");
check("B-1 平稳无异常图例", !(gold2.includes("存在") && gold2.includes("处异常")), "");

// B-2：gold 覆盖度相邻下降 >=5pt → 异常高亮 + 图例
clearStore();
renderTrendChart([
  { ts: "t1", gold_coverage: 90, f1_acc_before: 0.8, f1_acc_after: 0.85 },
  { ts: "t2", gold_coverage: 80, f1_acc_before: 0.8, f1_acc_after: 0.85 },
]);
const goldA = STORE["#trendGold"] || "";
check("B-2 覆盖度下降>=5 标记异常点(trend-anomaly)", goldA.includes("trend-anomaly"), "");
check("B-2 图例「存在 1 处异常」", goldA.includes("存在 1 处异常"), "");

// B-2：F1 后选对率相邻下降 >=0.1 → 异常高亮（trendF1 面板）
clearStore();
renderTrendChart([
  { ts: "t1", gold_coverage: 90, f1_acc_before: 0.8, f1_acc_after: 0.9 },
  { ts: "t2", gold_coverage: 90, f1_acc_before: 0.8, f1_acc_after: 0.7 },
]);
const f1A = STORE["#trendF1"] || "";
check("B-2 F1 后下降>=0.1 标记异常点", f1A.includes("trend-anomaly"), "");
check("B-2 F1 面板图例「存在 1 处异常」", f1A.includes("存在 1 处异常"), "");

console.log("");
console.log(failed === 0 ? "=== 前端验证：全部通过 ===" : `=== 前端验证：${failed} 项失败 ===`);
process.exit(failed === 0 ? 0 : 1);
