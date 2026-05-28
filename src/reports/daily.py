"""生成每日 Markdown 报告。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from src.advisor.advisor import AdviceResult
from src.analytics.portfolio import PortfolioSummary, WatchlistItem
from src.config_loader import ROOT, load_strategy

ACTION_LABELS = {
    "hold": "持有",
    "add": "加仓",
    "reduce": "减仓",
    "switch": "换基",
}


def _fmt_pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "—"
    prefix = "+" if signed and v > 0 else ""
    return f"{prefix}{v:.2f}%"


def _fmt_money(v: float, signed: bool = False) -> str:
    prefix = "+" if signed and v > 0 else ""
    return f"{prefix}{v:,.2f}"


def _render_rule_signals(advice: AdviceResult | None) -> list[str]:
    if not advice or not advice.rule_signals:
        return []
    lines = [
        "",
        "## 规则扫描",
        "",
        "| 级别 | 规则 | 基金 | 建议 | 说明 |",
        "|------|------|------|------|------|",
    ]
    for s in advice.rule_signals:
        code = s.fund_code or "—"
        lines.append(
            f"| {s.severity} | {s.rule_id} | {code} | "
            f"{ACTION_LABELS.get(s.suggested_action, s.suggested_action)} | {s.message} |"
        )
    return lines


def _render_news_section(advice: AdviceResult | None) -> list[str]:
    if not advice or not advice.news_digest:
        return []
    lines = [
        "",
        "## 相关要闻",
        "",
        "| 关键词 | 标题 | 摘要 | 时间 | 来源 |",
        "|--------|------|------|------|------|",
    ]
    for item in advice.news_digest:
        title = item.get("title", "")
        url = item.get("url", "")
        title_cell = f"[{title}]({url})" if url else title
        lines.append(
            f"| {item.get('keyword', '—')} | {title_cell} | "
            f"{item.get('summary', '—')} | {item.get('published_at', '—')} | "
            f"{item.get('source', '—')} |"
        )
    if advice.news_error:
        lines.extend(["", f"> 部分关键词拉取异常：{advice.news_error}", ""])
    else:
        lines.append("")
    return lines


def _render_trend_section(advice: AdviceResult | None) -> list[str]:
    trend = advice.trend_observation if advice else None
    if not trend or not trend.get("holdings"):
        return []
    lines = [
        "",
        "## 趋势观察",
        "",
        f"> {trend.get('philosophy', '').strip() or '阶段涨跌 + 回撤/反弹，仅供参考，不自动下单。'}",
        "",
        f"回看 **{trend.get('lookback_days', 90)}** 日；大涨/大跌阈值 **{trend.get('big_move_pct', 12)}%**，小回/小弹阈值 **{trend.get('small_correction_pct', 6)}%**。",
        "",
        "| 基金 | 阶段涨跌 | 自高点回落 | 自低点反弹 | 趋势 | 提示 |",
        "|------|----------|------------|------------|------|------|",
    ]
    for h in trend["holdings"]:
        lines.append(
            f"| {h.get('name', h.get('code', '—'))} | "
            f"{_fmt_pct(h.get('period_return_pct'))} | "
            f"{_fmt_pct(h.get('drawdown_from_peak_pct'))} | "
            f"{_fmt_pct(h.get('bounce_from_trough_pct'))} | "
            f"{h.get('trend_label', h.get('trend', '—'))} | {h.get('hint', '—')} |"
        )
    bench = trend.get("benchmark")
    if bench and bench.get("trend") != "insufficient_data":
        lines.extend(
            [
                "",
                f"**基准 {bench.get('name', '')}**：{bench.get('trend_label', '')} — {bench.get('hint', '')}",
                "",
            ]
        )
    else:
        lines.append("")
    return lines


def _render_ai_section(advice: AdviceResult | None) -> list[str]:
    if not advice:
        return []
    if advice.skipped:
        return [
            "",
            "## AI 建议",
            "",
            f"> {advice.skip_reason}",
            "",
        ]

    lines = [
        "",
        "## AI 市场总结",
        "",
        advice.market_summary,
        "",
        f"**整体风险判断**：{advice.overall_risk_level}",
        "",
        "## AI 操作建议",
        "",
        "| 基金 | 操作 | 比例 | 置信度 | 理由 |",
        "|------|------|------|--------|------|",
    ]
    if not advice.actions:
        lines.append("| — | 持有 | — | — | 暂无明确操作 |")
    for a in advice.actions:
        label = ACTION_LABELS.get(a["action"], a["action"])
        ratio = a.get("ratio")
        ratio_s = f"{ratio * 100:.0f}%" if ratio is not None else "—"
        lines.append(
            f"| {a['fund_code']} | {label} | {ratio_s} | {a.get('confidence', '—')} | {a.get('reason', '')} |"
        )

    if advice.switch_candidates:
        lines.extend(
            [
                "",
                "### 换基候选",
                "",
                "| 转出 | 转入 | 理由 |",
                "|------|------|------|",
            ]
        )
        for sw in advice.switch_candidates:
            lines.append(
                f"| {sw['from_fund_code']} | {sw['to_fund_code']} | {sw.get('reason', '')} |"
            )

    lines.extend(
        [
            "",
            "> 模式：advise_only — 仅供参考，执行前请自行确认。",
            "",
        ]
    )
    return lines


def render_daily_report(
    report_date: date,
    portfolio: PortfolioSummary,
    watchlist: list[WatchlistItem],
    data_as_of: str,
    advice: AdviceResult | None = None,
) -> str:
    strategy = load_strategy()
    benchmark_cfg = strategy.get("benchmark", {}).get("index_code", "000300.SH")
    b = portfolio.benchmark
    phase = "Phase 2（程序 + 规则 + AI）" if advice and not advice.skipped else (
        "Phase 2（程序 + 规则）" if advice else "Phase 1（程序计算）"
    )

    lines: list[str] = [
        f"# 基金日报 {report_date.isoformat()}",
        "",
        f"> 数据截至：{data_as_of}  |  模式：{phase}",
        "",
        "## 账户概览",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 总市值 | {_fmt_money(portfolio.total_market_value)} 元 |",
        f"| 总成本 | {_fmt_money(portfolio.total_cost_value)} 元 |",
        f"| 浮动盈亏 | {_fmt_money(portfolio.total_unrealized_pnl, signed=True)} 元 |",
        f"| 浮动收益率 | {_fmt_pct(portfolio.total_unrealized_pnl_pct)} |",
        "",
    ]

    if b:
        lines.extend(
            [
                "## 基准指数",
                "",
                f"- 基准：{b.name}（`{benchmark_cfg}`）",
                f"- 交易日：{b.trade_date}",
                f"- 收盘：{b.close:.2f}",
                f"- 日涨跌：{_fmt_pct(b.daily_change_pct)}",
            ]
        )
        if getattr(b, "data_source", None):
            lines.append(f"- 数据来源：{b.data_source}")
        lines.append("")

    lines.extend(
        [
            "## 持仓明细",
            "",
            "| 基金代码 | 名称 | 渠道 | 份额 | 最新净值 | 净值日期 | 日涨跌 | 市值 | 浮动盈亏 | 收益率 | 仓位 |",
            "|----------|------|------|------|----------|----------|--------|------|----------|--------|------|",
        ]
    )

    for p in portfolio.positions:
        lines.append(
            f"| {p.fund_code} | {p.fund_name} | {p.channel} | {p.shares} | "
            f"{p.unit_nav:.4f} | {p.nav_date} | {_fmt_pct(p.daily_growth_pct)} | "
            f"{_fmt_money(p.market_value)} | {_fmt_money(p.unrealized_pnl, signed=True)} | "
            f"{_fmt_pct(p.unrealized_pnl_pct)} | {p.weight_pct:.2f}% |"
        )

    lines.extend(_render_rule_signals(advice))
    lines.extend(_render_trend_section(advice))
    lines.extend(_render_news_section(advice))
    lines.extend(_render_ai_section(advice))

    if watchlist:
        lines.extend(
            [
                "",
                "## 关注池（未持仓）",
                "",
                "| 基金代码 | 名称 | 主题 | 风险 | 最新净值 | 净值日期 | 日涨跌 | 备注 |",
                "|----------|------|------|------|----------|----------|--------|------|",
            ]
        )
        for w in watchlist:
            lines.append(
                f"| {w.fund_code} | {w.fund_name} | {w.theme} | {w.risk_tag} | "
                f"{w.unit_nav:.4f} | {w.nav_date} | {_fmt_pct(w.daily_growth_pct)} | {w.notes or '—'} |"
            )

    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- 场外基金净值通常 **T 日收盘后 T+1 公布**，日涨跌以数据源「日增长率」或相邻两日净值计算为准。",
            "- 请与支付宝/天天基金持仓页面对照；若不一致，优先以交易平台为准并修正 `config/positions.csv`。",
            "- 本报告不构成投资建议；AI 建议可能出错，请以交易平台数据为准。",
            "",
        ]
    )
    if advice and advice.model:
        lines.insert(3, f"> AI 模型：{advice.model}  ")
    return "\n".join(lines)


def save_daily_report(content: str, report_date: date | None = None) -> Path:
    d = report_date or date.today()
    out_dir = ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{d.isoformat()}.md"
    path.write_text(content, encoding="utf-8")
    return path
