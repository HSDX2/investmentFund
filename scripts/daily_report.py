#!/usr/bin/env python3
"""生成基金每日报告（Phase 1 数据 + Phase 2 规则与 AI 建议）。

用法（在项目根目录）:
    python scripts/daily_report.py
    python scripts/daily_report.py --no-cache
    python scripts/daily_report.py --no-ai      # 仅程序+规则，不调用 LLM
    python scripts/daily_report.py --no-email   # 不发送邮件
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.advisor.advisor import generate_advice, save_advice_audit
from src.analytics.portfolio import build_portfolio_summary, build_watchlist
from src.collectors.index_benchmark import fetch_index_snapshot
from src.collectors.nav import fetch_fund_nav_history, get_fund_nav_snapshot
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
from src.reports.publish import footer_report_lines, publish_markdown_report


def main() -> int:
    parser = argparse.ArgumentParser(description="生成基金每日涨跌报告（含 AI 建议）")
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="忽略本地净值缓存，强制从网络重新拉取",
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
    for code in codes:
        try:
            if args.no_cache:
                df = fetch_fund_nav_history(code)
                cache = ROOT / "data" / "nav" / f"{code}.csv"
                cache.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(cache, index=False, encoding="utf-8-sig")
            nav_map[code] = get_fund_nav_snapshot(code, use_cache=not args.no_cache)
            snap = nav_map[code]
            print(f"  {code} 净值 {snap.unit_nav} ({snap.nav_date}) 日涨跌 {snap.daily_growth_pct}%")
        except Exception as e:
            print(f"  [失败] {code}: {e}")
            return 1

    benchmark = None
    index_code = strategy.get("benchmark", {}).get("index_code", "000300.SH")
    try:
        benchmark = fetch_index_snapshot(index_code)
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

    if advice.skipped:
        print(f"AI：已跳过 — {advice.skip_reason}")
    else:
        print(f"AI：已生成（模型 {advice.model}），{len(advice.actions)} 条操作")

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
            subject, plain, html_body = build_slim_daily_email(
                report_date,
                portfolio,
                checklist_items,
                advice,
                report_public_url=public_url,
                report_footer_plain=footer_plain,
                report_footer_html=footer_html,
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
