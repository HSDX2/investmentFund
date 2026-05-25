/* 基金投资面板 — 读取 docs/data/latest.json */

const COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f778ba", "#79c0ff", "#ffa657"];

let chartMain = null;
let chartPie = null;

function fmtPct(v, signed = true) {
  if (v == null || Number.isNaN(v)) return "—";
  const p = signed && v > 0 ? "+" : "";
  return `${p}${Number(v).toFixed(2)}%`;
}

function fmtMoney(v, signed = false) {
  if (v == null) return "—";
  const p = signed && v > 0 ? "+" : "";
  return `${p}${Number(v).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pctClass(v) {
  if (v == null) return "";
  return v >= 0 ? "rise" : "fall";
}

function dataUrl(name) {
  return new URL(`../data/${name}`, window.location.href).href;
}

async function loadManifest() {
  try {
    const r = await fetch(dataUrl("manifest.json"));
    if (!r.ok) return null;
    return r.json();
  } catch {
    return null;
  }
}

async function loadSnapshot(dateStr) {
  const file = dateStr ? `${dateStr}.json` : "latest.json";
  const r = await fetch(dataUrl(file));
  if (!r.ok) throw new Error(`无法加载 ${file}`);
  return r.json();
}

function renderMeta(data) {
  const line = [
    `数据截至 ${data.data_as_of}`,
    data.benchmark ? `${data.benchmark.name} ${fmtPct(data.benchmark.daily_change_pct)}` : null,
    data.generated_at ? `更新 ${data.generated_at.replace("T", " ")}` : null,
  ].filter(Boolean).join(" · ");
  document.getElementById("metaLine").textContent = line;

  const reportLink = document.getElementById("reportLink");
  reportLink.href = new URL(`../reports/${data.date}.html`, window.location.href).href;
}

function renderCards(data) {
  const p = data.portfolio;
  const est = p.estimated_daily_pct;
  const vs = p.vs_benchmark_daily_pct;
  const cards = [
    { label: "总市值", value: `${fmtMoney(p.total_market_value)} 元` },
    {
      label: "浮动盈亏",
      value: `${fmtMoney(p.total_unrealized_pnl, true)} 元`,
      sub: fmtPct(p.total_unrealized_pnl_pct),
      cls: pctClass(p.total_unrealized_pnl),
    },
    {
      label: "估算日涨跌",
      value: fmtPct(est),
      sub: vs != null ? `vs 基准 ${vs >= 0 ? "跑赢" : "跑输"} ${Math.abs(vs).toFixed(2)}%` : "",
      cls: pctClass(est),
    },
    {
      label: "AI 风险",
      value: data.advice?.overall_risk_level || "—",
      sub: data.advice?.skipped ? data.advice.skip_reason : "semi_auto 建议",
    },
  ];

  document.getElementById("summaryCards").innerHTML = cards
    .map(
      (c) => `
    <div class="card">
      <div class="label">${c.label}</div>
      <div class="value ${c.cls || ""}">${c.value}</div>
      ${c.sub ? `<div class="sub ${c.cls || ""}">${c.sub}</div>` : ""}
    </div>`
    )
    .join("");
}

function renderPositions(data) {
  const tbody = document.querySelector("#posTable tbody");
  tbody.innerHTML = data.portfolio.positions
    .map((p) => {
      const dayCls = pctClass(p.daily_growth_pct);
      const pnlCls = pctClass(p.unrealized_pnl);
      return `<tr>
      <td>${p.fund_code}</td>
      <td>${escapeHtml(p.fund_name)}</td>
      <td class="${dayCls}">${fmtPct(p.daily_growth_pct)}</td>
      <td class="${pnlCls}">${fmtMoney(p.unrealized_pnl, true)}</td>
      <td class="${pnlCls}">${fmtPct(p.unrealized_pnl_pct)}</td>
      <td>${p.weight_pct.toFixed(1)}%</td>
    </tr>`;
    })
    .join("");
}

function renderRules(data) {
  const ul = document.getElementById("ruleList");
  const signals = data.advice?.rule_signals || [];
  if (!signals.length) {
    ul.innerHTML = '<li class="empty">暂无规则信号</li>';
    return;
  }
  ul.innerHTML = signals
    .map(
      (s) =>
        `<li><span class="sev-${s.severity}">[${s.severity}]</span> ${escapeHtml(s.message)}</li>`
    )
    .join("");
}

function renderAi(data) {
  const el = document.getElementById("aiBlock");
  const a = data.advice;
  if (!a || a.skipped) {
    el.innerHTML = `<p class="empty">${escapeHtml(a?.skip_reason || "无 AI 建议")}</p>`;
    return;
  }
  const actions = (a.actions || [])
    .map(
      (x) =>
        `<div class="ai-action"><b>${x.fund_code}</b> ${x.action} · ${escapeHtml(x.reason || "")}</div>`
    )
    .join("");
  el.innerHTML = `<p>${escapeHtml(a.market_summary || "")}</p><div class="ai-actions">${actions || '<span class="empty">暂无操作</span>'}</div>`;
}

function renderNews(data) {
  const ul = document.getElementById("newsList");
  const items = data.advice?.news_digest || [];
  if (!items.length) {
    ul.innerHTML = '<li class="empty">暂无要闻</li>';
    return;
  }
  ul.innerHTML = items
    .slice(0, 8)
    .map((n) => {
      const title = escapeHtml(n.title || "");
      const sum = escapeHtml(n.summary || "");
      const link = n.url ? `<a href="${n.url}" target="_blank" rel="noopener">${title}</a>` : title;
      return `<li><span class="muted">[${escapeHtml(n.keyword || "")}]</span> ${link}<br><small>${sum}</small></li>`;
    })
    .join("");
}

function renderBatch(data) {
  const el = document.getElementById("batchBlock");
  const batch = data.batch_state;
  if (!batch?.batch_schedule?.length) {
    el.innerHTML = '<p class="empty">无分批计划（跑选基后生成）</p>';
    return;
  }
  const sent = new Set(batch.sent_offsets || []);
  const rows = batch.batch_schedule
    .filter((b) => b.batch !== "daily")
    .map((b) => {
      const done = sent.has(b.day_offset);
      return `<tr>
        <td>${escapeHtml(b.label || "")}</td>
        <td>${b.batch_total_cny?.toLocaleString() || "—"} 元</td>
        <td>${done ? "已提醒" : "待执行"}</td>
      </tr>`;
    })
    .join("");
  el.innerHTML = `<table class="batch-table"><thead><tr><th>批次</th><th>金额</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderCharts(data) {
  if (!chartMain) chartMain = echarts.init(document.getElementById("chartMain"));
  if (!chartPie) chartPie = echarts.init(document.getElementById("chartPie"));

  const charts = data.charts || {};
  const series = [];

  if (charts.portfolio_return_indexed?.length) {
    series.push({
      name: "账户估算",
      type: "line",
      smooth: true,
      showSymbol: false,
      data: charts.portfolio_return_indexed.map((p) => [p.date, p.value]),
      lineStyle: { width: 2.5 },
    });
  }

  if (charts.benchmark_return_indexed?.length) {
    series.push({
      name: data.benchmark?.name || "基准",
      type: "line",
      smooth: true,
      showSymbol: false,
      data: charts.benchmark_return_indexed.map((p) => [p.date, p.value]),
      lineStyle: { type: "dashed", width: 1.5 },
    });
  }

  const fundCurves = charts.fund_return_indexed || {};
  Object.entries(fundCurves).forEach(([code, pts], i) => {
    if (!pts?.length) return;
    series.push({
      name: code,
      type: "line",
      smooth: true,
      showSymbol: false,
      data: pts.map((p) => [p.date, p.value]),
      lineStyle: { width: 1, opacity: 0.65 },
      itemStyle: { color: COLORS[(i + 2) % COLORS.length] },
    });
  });

  chartMain.setOption({
    backgroundColor: "transparent",
    textStyle: { color: "#8b949e" },
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: "#8b949e" }, top: 0 },
    grid: { left: 48, right: 16, top: 40, bottom: 28 },
    xAxis: { type: "time", axisLine: { lineStyle: { color: "#2a3544" } } },
    yAxis: {
      type: "value",
      scale: true,
      axisLabel: { formatter: "{value}" },
      splitLine: { lineStyle: { color: "#2a3544" } },
    },
    series,
  });

  const pieData = data.portfolio.positions.map((p) => ({
    name: `${p.fund_code}`,
    value: p.market_value,
  }));
  chartPie.setOption({
    backgroundColor: "transparent",
    textStyle: { color: "#8b949e" },
    tooltip: { trigger: "item", formatter: "{b}: {c} 元 ({d}%)" },
    series: [
      {
        type: "pie",
        radius: ["42%", "68%"],
        data: pieData,
        label: { color: "#e6edf3", formatter: "{b}\n{d}%" },
        itemStyle: { borderColor: "#1a2332", borderWidth: 2 },
        color: COLORS,
      },
    ],
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function populateDateSelect(manifest, currentDate) {
  const sel = document.getElementById("dateSelect");
  const dates = manifest?.dates?.length ? manifest.dates : [currentDate];
  sel.innerHTML = dates
    .map((d) => `<option value="${d}" ${d === currentDate ? "selected" : ""}>${d}</option>`)
    .join("");
  sel.addEventListener("change", async () => {
    try {
      const data = await loadSnapshot(sel.value);
      renderAll(data);
    } catch (e) {
      document.getElementById("metaLine").textContent = e.message;
    }
  });
}

function renderAll(data) {
  renderMeta(data);
  renderCards(data);
  renderPositions(data);
  renderRules(data);
  renderAi(data);
  renderNews(data);
  renderBatch(data);
  renderCharts(data);
}

async function init() {
  try {
    const [manifest, data] = await Promise.all([loadManifest(), loadSnapshot()]);
    await populateDateSelect(manifest, data.date);
    renderAll(data);
  } catch (e) {
    document.getElementById("metaLine").innerHTML =
      `暂无数据：${escapeHtml(e.message)}。请先运行 <code>python scripts/daily_report.py</code> 生成快照。`;
  }
  window.addEventListener("resize", () => {
    chartMain?.resize();
    chartPie?.resize();
  });
}

init();
