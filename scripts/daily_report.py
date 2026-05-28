#!/usr/bin/env python3
"""生成基金每日报告（Phase 1 数据 + Phase 2 规则与 AI 建议）。

用法（在项目根目录）:
    python scripts/daily_report.py
    python scripts/daily_report.py --cache      # 调试：优先读本地净值缓存
    python scripts/daily_report.py --no-ai      # 仅程序+规则，不调用 LLM
    python scripts/daily_report.py --no-email   # 不发送邮件
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.advisor.advisor import generate_advice, save_advice_audit
from src.advisor.market_outlook import generate_market_outlook
from src.analytics.portfolio import build_portfolio_summary, build_watchlist
from src.analytics.recommendation_board import build_recommendation_board
from src.collectors.capital_flow import fetch_capital_flow_snapshot
from src.collectors.capital_flow_history import (
    build_flow_trends,
    fetch_northbound_history,
    load_flow_history,
    save_flow_snapshot,
)
from src.collectors.index_benchmark import fetch_index_snapshot
from src.collectors.data_quality import collect_stale_data_notes
from src.collectors.nav import get_fund_nav_snapshot
from src.config_loader import all_fund_codes, load_fund_universe, load_positions, load_strategy
from src.executor.checklist import (
    build_operation_checklist,
    render_checklist_markdown,
    save_checklist,
)
from src.notify.email import send_email
from src.notify.settings import load_email_settings
from src.notify.email_templates import build_slim_daily_email
from src.notify.batch_state import get_due_batch_today, mark_batch_sent
from src.notify.email_templates import build_batch_reminder_email
from src.reports.daily import render_daily_report, save_daily_report
from src.reports.dashboard_export import build_dashboard_payload, export_dashboard_json
from src.reports.publish import footer_report_lines, publish_markdown_report


def main() -> int:
    parser = argparse.ArgumentParser(description="生成基金每日涨跌报告（含 AI 建议）")
    parser.add_argument(
        "--cache",
        action="store_true",
        help="优先使用本地净值/指数缓存（默认每次从网络拉取最新）",
    )
    parser.add_argument(
        "--no-ai",
        action="store_true",
        help="不调用 LLM，仅生成数据与规则扫描",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="不发送 QQ 邮件推送",
    )
    args = parser.parse_args()

    positions = load_positions()
    universe = load_fund_universe()
    strategy = load_strategy()

    if not positions and not universe:
        print("错误：positions.csv 与 fund_universe.csv 均为空，请先填写配置。")
        return 1

    codes = all_fund_codes()
    print(f"正在拉取 {len(codes)} 只基金净值: {', '.join(codes)}")

    nav_map = {}
    for i, code in enumerate(codes):
        if i > 0:
            time.sleep(1.5)
        try:
            nav_map[code] = get_fund_nav_snapshot(code, use_cache=args.cache)
            snap = nav_map[code]
            src = f" [{snap.data_source}]" if snap.data_source else ""
            print(
                f"  {code} 净值 {snap.unit_nav} ({snap.nav_date}) "
                f"日涨跌 {snap.daily_growth_pct}%{src}"
            )
        except Exception as e:
            print(f"  [失败] {code}: {e}")
            return 1

    benchmark = None
    index_code = strategy.get("benchmark", {}).get("index_code", "000300.SH")
    try:
        benchmark = fetch_index_snapshot(index_code, use_cache=args.cache)
        print(f"基准 {benchmark.name} 收盘 {benchmark.close} ({benchmark.trade_date})")
    except Exception as e:
        print(f"警告：基准指数拉取失败 ({e})，报告中将省略基准段。")

    portfolio = build_portfolio_summary(positions, nav_map, benchmark)
    held = {p["fund_code"] for p in positions}
    watchlist = build_watchlist(universe, nav_map, held)

    latest_dates = [str(s.nav_date) for s in nav_map.values()]
    if benchmark:
        latest_dates.append(str(benchmark.trade_date))
    data_as_of = max(latest_dates) if latest_dates else date.today().isoformat()

    print("\n正在生成规则扫描与 AI 建议...")
    advice = generate_advice(
        date.today(),
        data_as_of,
        portfolio,
        watchlist,
        strategy,
        universe,
        positions,
        use_llm=not args.no_ai,
    )
    audit_path = save_advice_audit(advice)
    print(f"建议审计已保存: {audit_path}")

    capital_flow = None
    flow_trends = None
    recommendation_board = None
    if strategy.get("market_flow", {}).get("enabled", True):
        print("正在采集主力资金流向...")
        try:
            capital_flow = fetch_capital_flow_snapshot(strategy, positions, universe)
            if capital_flow.error and not capital_flow.data_source:
                print(f"  资金流：失败 — {capital_flow.error}")
            else:
                save_flow_snapshot(capital_flow)
                nb = capital_flow.northbound
                if nb and nb.disclosed and nb.total_net_yi is not None:
                    nb_txt = f"北向 {nb.total_net_yi:+.2f} 亿"
                elif nb and not nb.disclosed:
                    nb_txt = "北向 已暂停披露"
                else:
                    nb_txt = "北向 —"
                print(
                    f"  主力方向：{capital_flow.overall_label} · {nb_txt} · "
                    f"来源 {capital_flow.data_source or '—'}"
                )
                if capital_flow.error:
                    print(f"  部分失败：{capital_flow.error}")
        except Exception as e:
            print(f"  资金流：异常 — {e}")

        if strategy.get("recommendation_board", {}).get("enabled", True):
            hist_days = int(strategy.get("recommendation_board", {}).get("history_days", 30))
            history = load_flow_history(hist_days)
            nb_hist = fetch_northbound_history(hist_days)
            flow_trends = build_flow_trends(history, nb_hist, lookback_days=hist_days)
            recommendation_board = build_recommendation_board(
                strategy,
                watchlist,
                universe,
                positions,
                capital_flow,
                flow_trends,
                advice.news_digest,
            )
            print(
                f"推荐看板：基金 {len(recommendation_board.fund_picks)} 只 · "
                f"龙头 {len(recommendation_board.stock_picks)} 只 · "
                f"情绪 {recommendation_board.sentiment_label}"
            )

    market_outlook = generate_market_outlook(
        date.today().isoformat(),
        data_as_of,
        portfolio,
        capital_flow,
        advice.news_digest,
        strategy,
        positions,
        universe,
        use_llm=not args.no_ai,
    )
    if market_outlook.skipped:
        print(f"方向研判：已跳过 — {market_outlook.skip_reason}")
    else:
        print(
            f"方向研判：{market_outlook.overall_bias} "
            f"（置信 {market_outlook.confidence:.0%}，{market_outlook.horizon}）"
        )

    if advice.skipped:
        print(f"AI：已跳过 — {advice.skip_reason}")
    else:
        print(f"AI：已生成（模型 {advice.model}），{len(advice.actions)} 条操作")
    if advice.news_digest:
        llm_note = "含 LLM 摘要" if any(
            item.get("summary_source") == "llm" for item in advice.news_digest
        ) else "预览摘要"
        print(f"要闻：已采集 {len(advice.news_digest)} 条（{llm_note}）")
    elif strategy.get("news", {}).get("enabled"):
        print("要闻：未采集到相关新闻")

    content = render_daily_report(
        date.today(), portfolio, watchlist, data_as_of, advice=advice
    )
    out = save_daily_report(content)
    print(f"\n报告已生成: {out}")

    checklist_items = build_operation_checklist(
        portfolio, advice, positions, strategy
    )
    checklist_md = render_checklist_markdown(
        date.today(), checklist_items, advice, portfolio
    )
    checklist_path = save_checklist(checklist_md)
    print(f"操作清单已生成: {checklist_path}")

    report_date = date.today().isoformat()
    full_md = f"{content.rstrip()}\n\n{checklist_md.lstrip()}"
    html_path, _, public_url = publish_markdown_report(
        full_md,
        report_date,
        kind="daily",
        title=f"基金日报 {report_date}",
    )

    dash_payload = build_dashboard_payload(
        report_date,
        data_as_of,
        portfolio,
        watchlist,
        advice,
        positions,
        strategy,
        capital_flow=capital_flow,
        market_outlook=market_outlook,
        flow_trends=flow_trends,
        recommendation_board=recommendation_board,
    )
    dash_path, latest_path = export_dashboard_json(dash_payload, report_date)
    print(f"面板数据: {latest_path}")

    footer_plain, footer_html = footer_report_lines(public_url)
    if public_url:
        print(f"在线报告: {public_url}")
    else:
        print(f"HTML 报告: {html_path}（未配置 REPORT_PUBLIC_BASE_URL，邮件将附 HTML 附件）")

    if args.no_email:
        print("邮件：已跳过（--no-email）")
    else:
        email_cfg = load_email_settings()
        if not email_cfg.enabled:
            print("邮件：已禁用（config/notify.yaml 或 EMAIL_ENABLED=false）")
        elif not email_cfg.is_ready:
            print(
                "邮件：未发送 — 请在 .env 配置 SMTP_PASSWORD（QQ 邮箱授权码）"
                f"，收件人默认 {email_cfg.notify_to}"
            )
        else:
            dq_plain, dq_html = collect_stale_data_notes(nav_map, benchmark, data_as_of)
            subject, plain, html_body = build_slim_daily_email(
                report_date,
                portfolio,
                checklist_items,
                advice,
                report_public_url=public_url,
                report_footer_plain=footer_plain,
                report_footer_html=footer_html,
                data_quality_plain=dq_plain,
                data_quality_html=dq_html,
            )
            html_attachment = html_path.read_text(encoding="utf-8")
            try:
                send_email(
                    email_cfg,
                    subject,
                    plain,
                    html_body,
                    attachments=[(f"基金日报-{report_date}.html", html_attachment, "html")],
                )
                print(f"邮件：已发送至 {email_cfg.notify_to}（精简日报）")
            except Exception as e:
                print(f"邮件：发送失败 — {e}")
                return 1

            due_batch = get_due_batch_today()
            if due_batch:
                b_subj, b_plain, b_html = build_batch_reminder_email(due_batch)
                try:
                    send_email(email_cfg, b_subj, b_plain, b_html)
                    mark_batch_sent(int(due_batch["day_offset"]))
                    print(f"邮件：分批提醒已发送（{due_batch.get('label')}）")
                except Exception as e:
                    print(f"邮件：分批提醒发送失败 — {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
