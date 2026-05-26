/* 基金投资面板 — 读取 docs/data/latest.json */

const COLORS = ["#58a6ff", "#3fb950", "#d29922", "#f778ba", "#79c0ff", "#ffa657"];

let chartMain = null;
let chartPie = null;
let chartFlowIn = null;
let chartFlowOut = null;
let chartFlowHist = null;
let chartHotSectors = null;

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

function biasLabel(bias) {
  return { bullish: "偏多", neutral: "中性", bearish: "偏空" }[bias] || bias || "—";
}

function biasClass(bias) {
  return `bias-${bias || "neutral"}`;
}

function flowDirLabel(dir) {
  return { inflow: "净流入", outflow: "净流出", neutral: "中性" }[dir] || dir || "—";
}

function renderFlow(data) {
  const flow = data.market_flow;
  const summaryEl = document.getElementById("flowSummary");
  const themeEl = document.getElementById("themeFlowBlock");

  if (!flow || (flow.error && !flow.top_inflows?.length)) {
    summaryEl.innerHTML = `<p class="empty">${escapeHtml(flow?.error || "暂无资金流数据")}</p>`;
    themeEl.innerHTML = "";
    if (chartFlowIn) chartFlowIn.clear();
    if (chartFlowOut) chartFlowOut.clear();
    return;
  }

  const nb = flow.northbound;
  const sb = flow.southbound;
  const nbChip = nb
    ? nb.disclosed === false
      ? {
          label: `北向净买额（${nb.trade_date}）`,
          value: "已暂停披露",
          sub: "2024-08 起交易所不再公布日度净买额",
          cls: "",
        }
      : {
          label: `北向资金（${nb.trade_date}）`,
          value: `${nb.total_net_yi >= 0 ? "+" : ""}${Number(nb.total_net_yi).toFixed(2)} 亿`,
          sub: `沪 ${nb.sh_net_yi >= 0 ? "+" : ""}${Number(nb.sh_net_yi).toFixed(2)} · 深 ${nb.sz_net_yi >= 0 ? "+" : ""}${Number(nb.sz_net_yi).toFixed(2)}`,
          cls: nb.total_net_yi >= 0 ? "rise" : nb.total_net_yi < 0 ? "fall" : "",
        }
    : null;
  const sbChip =
    sb && sb.total_net_yi != null
      ? {
          label: `南向资金（${sb.trade_date}）`,
          value: `${sb.total_net_yi >= 0 ? "+" : ""}${Number(sb.total_net_yi).toFixed(2)} 亿`,
          sub: `港股通沪 ${sb.sh_net_yi >= 0 ? "+" : ""}${Number(sb.sh_net_yi || 0).toFixed(2)} · 深 ${sb.sz_net_yi >= 0 ? "+" : ""}${Number(sb.sz_net_yi || 0).toFixed(2)}`,
          cls: sb.total_net_yi >= 0 ? "rise" : sb.total_net_yi < 0 ? "fall" : "",
        }
      : null;

  const chips = [
    {
      label: "主力方向",
      value: flow.overall_label || flowDirLabel(flow.overall_direction),
      cls: flow.overall_direction === "inflow" ? "rise" : flow.overall_direction === "outflow" ? "fall" : "",
    },
    nbChip,
    sbChip,
    { label: "数据日期", value: flow.trade_date || "—" },
  ].filter(Boolean);

  let noteHtml = "";
  if (nb?.note) {
    noteHtml = `<p class="hint">${escapeHtml(nb.note)}</p>`;
  }

  summaryEl.innerHTML = `${noteHtml}${chips
    .map(
      (c) => `<div class="flow-chip">
      <span class="muted">${c.label}</span>
      <b class="${c.cls || ""}">${escapeHtml(c.value)}</b>
      ${c.sub ? `<small class="${c.cls || ""}">${escapeHtml(c.sub)}</small>` : ""}
    </div>`
    )
    .join("")}`;

  if (flow.theme_relevant?.length) {
    const rows = flow.theme_relevant
      .map(
        (t) => `<tr>
        <td>${escapeHtml(t.name)}</td>
        <td>${t.flow_type === "concept" ? "概念" : "行业"}</td>
        <td class="${t.net_inflow_yi >= 0 ? "rise" : "fall"}">${t.net_inflow_yi >= 0 ? "+" : ""}${t.net_inflow_yi.toFixed(2)} 亿</td>
        <td class="${pctClass(t.change_pct)}">${fmtPct(t.change_pct)}</td>
      </tr>`
      )
      .join("");
    themeEl.innerHTML = `<h3 class="hint">持仓相关板块</h3>
      <table><thead><tr><th>板块</th><th>类型</th><th>净流入</th><th>涨跌</th></tr></thead><tbody>${rows}</tbody></table>`;
  } else {
    themeEl.innerHTML = "";
  }

  renderFlowCharts(flow);
}

function renderFlowCharts(flow) {
  if (!chartFlowIn) chartFlowIn = echarts.init(document.getElementById("chartFlowIn"));
  if (!chartFlowOut) chartFlowOut = echarts.init(document.getElementById("chartFlowOut"));

  const inData = (flow.top_inflows || []).slice(0, 5).map((x) => ({
    name: x.name,
    value: Math.abs(x.net_inflow_yi),
    raw: x.net_inflow_yi,
  }));
  const outData = (flow.top_outflows || []).slice(0, 5).map((x) => ({
    name: x.name,
    value: Math.abs(x.net_inflow_yi),
    raw: x.net_inflow_yi,
  }));

  const barOption = (title, items, color) => ({
    backgroundColor: "transparent",
    title: { text: title, left: 0, textStyle: { color: "#8b949e", fontSize: 13 } },
    textStyle: { color: "#8b949e" },
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const p = params[0];
        const raw = items[p.dataIndex]?.raw ?? p.value;
        return `${p.name}<br/>${raw >= 0 ? "+" : ""}${raw.toFixed(2)} 亿`;
      },
    },
    grid: { left: 100, right: 16, top: 36, bottom: 20 },
    xAxis: {
      type: "value",
      axisLabel: { formatter: "{value} 亿" },
      splitLine: { lineStyle: { color: "#2a3544" } },
    },
    yAxis: {
      type: "category",
      data: items.map((x) => x.name).reverse(),
      axisLabel: { width: 80, overflow: "truncate" },
    },
    series: [
      {
        type: "bar",
        data: items.map((x) => x.value).reverse(),
        itemStyle: { color },
        label: {
          show: true,
          position: "right",
          formatter: (p) => {
            const raw = items[items.length - 1 - p.dataIndex]?.raw ?? p.value;
            return `${raw >= 0 ? "+" : ""}${raw.toFixed(1)}`;
          },
          color: "#e6edf3",
        },
      },
    ],
  });

  chartFlowIn.setOption(barOption("净流入 TOP", inData, "#ff4d4f"));
  chartFlowOut.setOption(barOption("净流出 TOP", outData, "#52c41a"));
}

function renderOutlook(data) {
  const el = document.getElementById("outlookBlock");
  const o = data.market_outlook;
  if (!o) {
    el.innerHTML = '<p class="empty">暂无方向研判（需运行日报并开启 market_outlook）</p>';
    return;
  }
  if (o.skipped && !o.capital_flow_view && !o.policy_event_view) {
    el.innerHTML = `<p class="empty">${escapeHtml(o.skip_reason || "方向研判已跳过")}</p>`;
    return;
  }

  const themes = (o.theme_outlook || [])
    .map(
      (t) => `<div class="outlook-theme">
      <span class="${biasClass(t.bias)}">${escapeHtml(t.theme)} · ${biasLabel(t.bias)}</span>
      <div>${escapeHtml(t.reason || "")}</div>
    </div>`
    )
    .join("");

  const risks = (o.key_risks || [])
    .map((r) => `<li>${escapeHtml(r)}</li>`)
    .join("");

  el.innerHTML = `
    <div class="outlook-meta">
      <span class="outlook-tag ${biasClass(o.overall_bias)}">整体 ${biasLabel(o.overall_bias)}</span>
      <span class="outlook-tag">周期 ${escapeHtml(o.horizon || "—")}</span>
      <span class="outlook-tag">置信度 ${Math.round((o.confidence || 0) * 100)}%</span>
      ${o.skipped ? `<span class="outlook-tag">规则摘要</span>` : `<span class="outlook-tag">AI 分析</span>`}
    </div>
    <p><b>资金面</b> ${escapeHtml(o.capital_flow_view || "—")}</p>
    <p><b>政策与事件</b> ${escapeHtml(o.policy_event_view || "—")}</p>
    ${themes ? `<div class="outlook-themes">${themes}</div>` : ""}
    ${risks ? `<ul class="outlook-risks">${risks}</ul>` : ""}
    <p class="outlook-disclaimer">${escapeHtml(o.disclaimer || "不构成投资建议")}</p>
  `;
}

function actionLabel(action) {
  return { buy: "买入", add: "加仓", hold: "持有", watch: "关注", dca: "定投" }[action] || action;
}

function renderReasonList(reasons) {
  if (!reasons?.length) return '<li class="empty">暂无结构化理由</li>';
  return reasons
    .map((r) => {
      const cls = r.type ? `reason-${r.type}` : "";
      const label = r.label ? `<b>${escapeHtml(r.label)}</b> · ` : "";
      return `<li class="${cls}">${label}${escapeHtml(r.detail || "")}</li>`;
    })
    .join("");
}

function renderRecommendationBoard(data) {
  const board = data.recommendation_board;
  const sentimentEl = document.getElementById("recSentiment");
  const fundEl = document.getElementById("fundRecList");
  const stockEl = document.getElementById("stockRecList");

  if (!board) {
    sentimentEl.innerHTML = '<p class="empty">暂无推荐看板数据</p>';
    fundEl.innerHTML = "";
    stockEl.innerHTML = "";
    return;
  }

  const weeklyNote = board.weekly_recommend_date
    ? ` · 含 ${board.weekly_recommend_date} 每周选基`
    : "";
  sentimentEl.innerHTML = `
    <div class="outlook-meta">
      <span class="outlook-tag">情绪 ${board.sentiment_score} · ${escapeHtml(board.sentiment_label || "")}</span>
      ${weeklyNote ? `<span class="outlook-tag">${escapeHtml(weeklyNote.replace(" · ", ""))}</span>` : ""}
    </div>
    <p>${escapeHtml(board.sentiment_summary || "")}</p>
  `;

  const funds = board.fund_picks || [];
  fundEl.innerHTML = funds.length
    ? funds
        .map(
          (f) => `<div class="rec-card">
        <div class="rec-card-head">
          <div><b>${f.fund_code}</b> ${escapeHtml(f.fund_name)}<div class="rec-meta">${escapeHtml(f.theme || "")} · ${f.source === "weekly" ? "每周选基" : "日度匹配"}</div></div>
          <span class="tag-action">${actionLabel(f.action)}</span>
        </div>
        <ul class="rec-reasons">${renderReasonList(f.reasons)}</ul>
      </div>`
        )
        .join("")
    : '<p class="empty">暂无基金推荐（需资金流与主题匹配）</p>';

  const stocks = board.stock_picks || [];
  stockEl.innerHTML = stocks.length
    ? stocks
        .map(
          (s) => `<div class="rec-card">
        <div class="rec-card-head">
          <div><b>${escapeHtml(s.name)}</b><div class="rec-meta">${escapeHtml(s.sector)} · ${s.flow_type === "concept" ? "概念" : "行业"} · 板块净流入 ${s.sector_net_yi >= 0 ? "+" : ""}${s.sector_net_yi.toFixed(2)} 亿</div></div>
          <span class="tag-action ${s.leader_change_pct >= 0 ? "rise" : "fall"}">${fmtPct(s.leader_change_pct)}</span>
        </div>
        <ul class="rec-reasons">${renderReasonList(s.reasons)}</ul>
      </div>`
        )
        .join("")
    : '<p class="empty">暂无龙头数据（行业接口需返回领涨股）</p>';
}

function renderFlowHistory(data) {
  const trends = data.flow_trends;
  const summaryEl = document.getElementById("flowHistSummary");
  if (!trends) {
    summaryEl.innerHTML = '<p class="empty">历史数据积累中（需连续运行日报）</p>';
    if (chartFlowHist) chartFlowHist.clear();
    if (chartHotSectors) chartHotSectors.clear();
    return;
  }

  const nbDisclosed = trends.northbound_disclosed !== false && (trends.northbound_series || []).length > 0;
  const chips = [
    { label: "快照天数", value: `${trends.snapshot_days || 0} 天` },
    nbDisclosed
      ? {
          label: "北向近5日",
          value: `${trends.northbound_sum_5d_yi >= 0 ? "+" : ""}${(trends.northbound_sum_5d_yi || 0).toFixed(2)} 亿`,
          cls: pctClass(trends.northbound_sum_5d_yi),
        }
      : { label: "北向近5日", value: "已暂停披露", cls: "" },
    nbDisclosed
      ? {
          label: "北向近10日",
          value: `${trends.northbound_sum_10d_yi >= 0 ? "+" : ""}${(trends.northbound_sum_10d_yi || 0).toFixed(2)} 亿`,
          cls: pctClass(trends.northbound_sum_10d_yi),
        }
      : { label: "北向近10日", value: "—", cls: "" },
    { label: "主力方向5日均", value: `${(trends.direction_avg_5d || 0) >= 0 ? "+" : ""}${(trends.direction_avg_5d || 0).toFixed(2)}` },
  ];
  const note = trends.northbound_note || (trends.northbound_hist_end ? `官方日度北向净买额止于 ${trends.northbound_hist_end}` : "");
  const chipsHtml = chips
    .map(
      (c) => `<div class="flow-chip"><span class="muted">${c.label}</span><b class="${c.cls || ""}">${escapeHtml(c.value)}</b></div>`
    )
    .join("");
  summaryEl.innerHTML = (note ? `<p class="hint">${escapeHtml(note)}</p>` : "") + chipsHtml;

  if (!chartFlowHist) chartFlowHist = echarts.init(document.getElementById("chartFlowHist"));
  if (!chartHotSectors) chartHotSectors = echarts.init(document.getElementById("chartHotSectors"));

  const nb = trends.northbound_series || [];
  const daily = trends.daily_series || [];
  const histSeries = nb.length
    ? [
        {
          name: "北向净买额（历史）",
          type: "bar",
          data: nb.map((p) => [p.date, p.net_yi]),
          itemStyle: {
            color: (p) => (p.value[1] >= 0 ? "#ff4d4f" : "#52c41a"),
          },
        },
      ]
    : [];

  chartFlowHist.setOption({
    backgroundColor: "transparent",
    textStyle: { color: "#8b949e" },
    tooltip: { trigger: "axis" },
    legend: { textStyle: { color: "#8b949e" }, top: 0 },
    grid: { left: 48, right: 16, top: 40, bottom: 28 },
    xAxis: { type: "time", axisLine: { lineStyle: { color: "#2a3544" } } },
    yAxis: {
      type: "value",
      name: nb.length ? "亿元" : "方向",
      splitLine: { lineStyle: { color: "#2a3544" } },
    },
    series: [
      ...histSeries,
      {
        name: "A股主力方向（行业/概念）",
        type: "line",
        yAxisIndex: 0,
        smooth: true,
        showSymbol: true,
        data: daily.map((p) => [
          p.date,
          p.overall_direction === "inflow" ? 1 : p.overall_direction === "outflow" ? -1 : 0,
        ]),
        lineStyle: { width: 2, color: "#58a6ff" },
        itemStyle: { color: "#58a6ff" },
      },
    ],
  });

  const hot = trends.hot_sectors || [];
  chartHotSectors.setOption({
    backgroundColor: "transparent",
    title: { text: "阶段吸金板块（累计净流入）", left: 0, textStyle: { color: "#8b949e", fontSize: 13 } },
    textStyle: { color: "#8b949e" },
    tooltip: { trigger: "axis" },
    grid: { left: 100, right: 16, top: 36, bottom: 20 },
    xAxis: { type: "value", splitLine: { lineStyle: { color: "#2a3544" } } },
    yAxis: {
      type: "category",
      data: hot.map((h) => h.name).reverse(),
      axisLabel: { width: 90, overflow: "truncate" },
    },
    series: [
      {
        type: "bar",
        data: hot.map((h) => h.cumulative_net_yi).reverse(),
        itemStyle: { color: "#58a6ff" },
        label: { show: true, position: "right", color: "#e6edf3" },
      },
    ],
  });
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
      label: "主力方向",
      value: data.market_flow?.overall_label || flowDirLabel(data.market_flow?.overall_direction) || "—",
      sub: data.market_outlook?.overall_bias
        ? `AI ${biasLabel(data.market_outlook.overall_bias)}`
        : "",
      cls:
        data.market_flow?.overall_direction === "inflow"
          ? "rise"
          : data.market_flow?.overall_direction === "outflow"
            ? "fall"
            : "",
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
  renderRecommendationBoard(data);
  renderFlowHistory(data);
  renderFlow(data);
  renderOutlook(data);
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
    chartFlowIn?.resize();
    chartFlowOut?.resize();
    chartFlowHist?.resize();
    chartHotSectors?.resize();
  });
}

init();
