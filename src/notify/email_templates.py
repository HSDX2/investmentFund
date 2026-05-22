"""邮件正文构建：精简日报、周报选基、分批提醒。"""

from __future__ import annotations

import html
import re
from typing import Any

from src.advisor.advisor import AdviceResult
from src.analytics.portfolio import PortfolioSummary
from src.executor.checklist import OperationItem
from src.notify.email import ACTION_LABELS, _checklist_rows_html


def _truncate_summary(text: str, max_sentences: int = 3, max_chars: int = 200) -> str:
    if not text:
        return "（暂无 AI 摘要）"
    parts = re.split(r"(?<=[。！？])\s*", text.strip())
    short = "".join(parts[:max_sentences]).strip()
    if len(short) > max_chars:
        short = short[: max_chars - 1] + "…"
    return short or text[:max_chars]


def _one_line_conclusion(
    advice: AdviceResult | None,
    checklist_items: list[OperationItem],
) -> tuple[str, str]:
    """返回 (操作标签, 一句话理由)。"""
    actionable = [op for op in checklist_items if op.action != "hold"]
    if actionable:
        op = actionable[0]
        label = ACTION_LABELS.get(op.action, op.action)
        reason = op.reason or (op.steps[0] if op.steps else "")
        return label, reason[:100]

    if advice and advice.actions:
        a = advice.actions[0]
        label = ACTION_LABELS.get(a.get("action", "hold"), "持有")
        return label, str(a.get("reason") or "")[:100]

    return "持有", "暂无明确操作；270042 日定投照常即可"


def _portfolio_daily_pct(portfolio: PortfolioSummary) -> float | None:
    acc = sum(
        (p.weight_pct / 100) * p.daily_growth_pct
        for p in portfolio.positions
        if p.daily_growth_pct is not None
    )
    return round(acc, 2) if portfolio.positions else None


def _benchmark_line(portfolio: PortfolioSummary) -> str:
    b = portfolio.benchmark
    if not b or b.daily_change_pct is None:
        return ""
    port_day = _portfolio_daily_pct(portfolio)
    if port_day is None:
        return f"沪深300 今日 {b.daily_change_pct:+.2f}%"
    diff = port_day - b.daily_change_pct
    word = "跑赢" if diff > 0 else ("跑输" if diff < 0 else "持平")
    return f"沪深300 {b.daily_change_pct:+.2f}% · 持仓估算 {port_day:+.2f}% · {word} {abs(diff):.2f}%"


def _positions_table_html(portfolio: PortfolioSummary) -> str:
    rows = []
    for p in portfolio.positions:
        day = f"{p.daily_growth_pct:+.2f}%" if p.daily_growth_pct is not None else "—"
        rows.append(
            f"<tr><td>{html.escape(p.fund_code)}</td>"
            f"<td>{html.escape(p.fund_name)}</td>"
            f"<td>{day}</td>"
            f"<td>{p.unrealized_pnl:+.2f}</td>"
            f"<td>{p.unrealized_pnl_pct:+.2f}%</td>"
            f"<td>{p.weight_pct:.1f}%</td></tr>"
        )
    return (
        "<table border='1' cellpadding='6' cellspacing='0' "
        "style='border-collapse:collapse;width:100%;font-size:13px'>"
        "<tr style='background:#f0f0f0'>"
        "<th>代码</th><th>名称</th><th>日涨跌</th><th>浮盈(元)</th><th>收益率</th><th>仓位</th>"
        "</tr>"
        + "".join(rows)
        + "</table>"
    )


def _rule_lines(advice: AdviceResult | None) -> list[str]:
    if not advice:
        return []
    return [
        f"[{s.severity}] {s.message}"
        for s in advice.rule_signals
        if s.severity in ("warning", "critical")
    ]


def _news_lines(advice: AdviceResult | None, limit: int = 3) -> list[str]:
    if not advice or not advice.news_digest:
        return []
    lines: list[str] = []
    for item in advice.news_digest[:limit]:
        kw = item.get("keyword", "")
        text = item.get("summary") or item.get("title", "")
        lines.append(f"· [{kw}] {text}")
    return lines


def build_slim_daily_email(
    report_date: str,
    portfolio: PortfolioSummary,
    checklist_items: list[OperationItem],
    advice: AdviceResult | None,
    *,
    report_public_url: str | None = None,
    report_footer_plain: str = "",
    report_footer_html: str = "",
    data_quality_plain: str = "",
    data_quality_html: str = "",
) -> tuple[str, str, str]:
    """返回 (subject, plain, html)。"""
    action_label, action_reason = _one_line_conclusion(advice, checklist_items)
    summary = _truncate_summary(advice.market_summary if advice else "")
    bench = _benchmark_line(portfolio)
    rules = _rule_lines(advice)
    news = _news_lines(advice)

    pnl_sign = "+" if portfolio.total_unrealized_pnl_pct >= 0 else ""
    subject = (
        f"【持仓】{report_date[5:]} "
        f"浮盈{pnl_sign}{portfolio.total_unrealized_pnl_pct:.1f}% · {action_label}"
    )

    plain_parts = [
        f"【结论】{action_label} — {action_reason}",
        "",
        f"账户 {portfolio.total_market_value:,.2f} 元 | "
        f"浮动 {portfolio.total_unrealized_pnl:+,.2f} 元（{portfolio.total_unrealized_pnl_pct:+.2f}%）",
    ]
    if bench:
        plain_parts.append(bench)
    plain_parts.extend(["", f"【摘要】{summary}", ""])
    if news:
        plain_parts.append("【要闻】")
        plain_parts.extend(f"  {line}" for line in news)
        plain_parts.append("")
    plain_parts.append("【持仓】")
    for p in portfolio.positions:
        day = f"{p.daily_growth_pct:+.2f}%" if p.daily_growth_pct is not None else "—"
        plain_parts.append(
            f"  {p.fund_code} {p.fund_name}  日{day}  浮盈{p.unrealized_pnl:+.2f}  仓位{p.weight_pct:.1f}%"
        )
    plain_parts.extend(["", "【今日操作】"])
    if not checklist_items or all(op.action == "hold" for op in checklist_items):
        plain_parts.append("  无；270042 日定投 10 元继续")
    else:
        for op in checklist_items:
            if op.action == "hold":
                continue
            label = ACTION_LABELS.get(op.action, op.action)
            plain_parts.append(f"  {label} {op.fund_name}({op.fund_code}) @ {op.channel}")
            for step in op.steps[:3]:
                plain_parts.append(f"    {step}")

    if rules:
        plain_parts.extend(["", "【规则提醒】", *[f"  - {r}" for r in rules]])

    if data_quality_plain:
        plain_parts.extend(["", data_quality_plain])

    plain_parts.extend(["", report_footer_plain or "完整报告见邮件附件。", "不构成投资建议。"])
    plain = "\n".join(plain_parts)

    rules_html = ""
    if rules:
        rules_html = "<h3>规则提醒</h3><ul>" + "".join(
            f"<li>{html.escape(r)}</li>" for r in rules
        ) + "</ul>"

    news_html = ""
    if news:
        news_html = "<h3>相关要闻</h3><ul>" + "".join(
            f"<li>{html.escape(line)}</li>" for line in news
        ) + "</ul>"

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Microsoft YaHei,sans-serif;line-height:1.6;color:#222;max-width:640px">
  <p style="font-size:16px"><b>【结论】{html.escape(action_label)}</b> — {html.escape(action_reason)}</p>
  <p>
    账户 <b>{portfolio.total_market_value:,.2f}</b> 元 ·
    浮动 <b>{portfolio.total_unrealized_pnl:+,.2f}</b> 元（{portfolio.total_unrealized_pnl_pct:+.2f}%）
  </p>
  {f'<p style="color:#555">{html.escape(bench)}</p>' if bench else ''}
  <p style="background:#f8f8f8;padding:10px;border-radius:6px">{html.escape(summary)}</p>
  {news_html}
  <h3>持仓</h3>
  {_positions_table_html(portfolio)}
  <h3>今日操作</h3>
  {_checklist_rows_html(checklist_items) if any(op.action != 'hold' for op in checklist_items) else '<p>无；270042 日定投 10 元继续</p>'}
  {rules_html}
  {data_quality_html}
  {report_footer_html}
  <p style="color:#888;font-size:12px;margin-top:16px">不构成投资建议</p>
</body></html>"""

    return subject, plain, html_body


def build_weekly_recommend_email(
    report_date: str,
    result: dict[str, Any],
    next_batch: dict[str, Any] | None,
    dca_note: str,
    *,
    report_public_url: str | None = None,
    report_footer_plain: str = "",
    report_footer_html: str = "",
) -> tuple[str, str, str]:
    """从 FundRecommendResult.to_dict() 构建周报邮件。"""
    budget = result.get("budget_cny", 0)
    summary = _truncate_summary(result.get("summary", ""), max_sentences=4, max_chars=280)
    recs = result.get("recommendations") or []

    subject = f"【选基】{report_date[5:]} 配置建议 · 预算 {budget:,.0f} 元"

    plain = [f"【配置思路】{summary}", "", "【建议清单】"]
    for r in recs:
        broad = "宽基" if r.get("is_broad_index") else "主题"
        plain.append(
            f"  {r['fund_code']} {r['fund_name']} | {r['action']} {r['amount_cny']:,.0f}元 | {broad} | {r.get('reason','')[:60]}"
        )
    if next_batch:
        plain.extend(["", f"【下一批】{next_batch.get('label', '')}"])
        for item in next_batch.get("items", []):
            plain.append(
                f"  {item['fund_code']} {item.get('fund_name','')} {item['action']} {item['amount_cny']:,.0f}元"
            )
    plain.extend(["", f"【定投】{dca_note}"])
    if report_footer_plain:
        plain.extend(["", report_footer_plain])
    elif report_public_url:
        plain.extend(["", f"完整报告：{report_public_url}"])
    else:
        plain.extend(["", "完整报告见邮件附件「选基报告.html」"])
    plain_text = "\n".join(plain)

    rows = ""
    for r in recs:
        broad = "✓" if r.get("is_broad_index") else "—"
        rows += (
            f"<tr><td>{html.escape(r['fund_code'])}</td>"
            f"<td>{html.escape(r['fund_name'])}</td>"
            f"<td>{html.escape(r['action'])}</td>"
            f"<td>{r['amount_cny']:,.0f}</td>"
            f"<td>{broad}</td>"
            f"<td>{html.escape(str(r.get('reason',''))[:80])}</td></tr>"
        )

    next_html = ""
    if next_batch:
        next_html = f"<h3>{html.escape(next_batch.get('label','下一批'))}</h3><ul>"
        for item in next_batch.get("items", []):
            next_html += (
                f"<li>{html.escape(item['fund_code'])} "
                f"{html.escape(item.get('fund_name',''))} — "
                f"{item['amount_cny']:,.0f} 元</li>"
            )
        next_html += "</ul>"

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Microsoft YaHei,sans-serif;line-height:1.6;color:#222;max-width:640px">
  <h2>每周选基 {html.escape(report_date)}</h2>
  <p>{html.escape(summary)}</p>
  <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px">
    <tr style="background:#f0f0f0"><th>代码</th><th>名称</th><th>操作</th><th>金额</th><th>宽基</th><th>理由</th></tr>
    {rows}
  </table>
  {next_html}
  <p><b>定投</b>：{html.escape(dca_note)}</p>
  {report_footer_html or (f'<p><a href="{report_public_url}" style="color:#0969da;font-weight:bold">📊 点击查看完整选基报告</a></p>' if report_public_url else '<p style="color:#888">完整报告见邮件附件 <b>选基报告.html</b></p>')}
</body></html>"""

    return subject, plain_text, html_body


def build_batch_reminder_email(batch: dict[str, Any]) -> tuple[str, str, str]:
    """分批到期提醒邮件。"""
    label = batch.get("label") or f"第{batch.get('batch_num')}批"
    total = batch.get("batch_total_cny", 0)
    subject = f"【分批提醒】{label} · 合计 {total:,.0f} 元"

    plain_lines = [f"今日建议执行：{label}", f"合计约 {total:,.0f} 元", "", "明细："]
    for item in batch.get("items", []):
        plain_lines.append(
            f"  {item['fund_code']} {item.get('fund_name','')} | "
            f"{item.get('action','buy')} | {item['amount_cny']:,.0f} 元"
        )
    plain_lines.extend(
        [
            "",
            "渠道：支付宝 → 我的 / 搜索基金代码 → 申购或加仓",
            "不构成投资建议。",
        ]
    )
    plain = "\n".join(plain_lines)

    rows = ""
    for item in batch.get("items", []):
        rows += (
            f"<tr><td>{html.escape(item['fund_code'])}</td>"
            f"<td>{html.escape(item.get('fund_name',''))}</td>"
            f"<td>{html.escape(item.get('action',''))}</td>"
            f"<td>{item['amount_cny']:,.0f}</td></tr>"
        )

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Microsoft YaHei,sans-serif;line-height:1.6;color:#222">
  <h2>分批买入提醒</h2>
  <p><b>{html.escape(label)}</b> — 合计 <b>{total:,.0f}</b> 元</p>
  <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse">
    <tr style="background:#f0f0f0"><th>代码</th><th>名称</th><th>操作</th><th>金额(元)</th></tr>
    {rows}
  </table>
  <p>请在支付宝手动确认申购/加仓。</p>
</body></html>"""

    return subject, plain, html_body


def get_next_batch_from_schedule(batch_schedule: list[dict]) -> dict | None:
    """取第一个非 daily 的批次作为「下一批」展示（周报用）。"""
    for b in batch_schedule:
        if b.get("batch") != "daily":
            return b
    return None
