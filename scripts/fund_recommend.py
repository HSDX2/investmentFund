#!/usr/bin/env python3
"""全市场基金筛选 + AI 推荐（独立于每日持仓日报）。

用法:
    python scripts/fund_recommend.py
    python scripts/fund_recommend.py --no-cache
    python scripts/fund_recommend.py --no-ai     # 只看筛选 Top 列表
    python scripts/fund_recommend.py --budget 5000
    python scripts/fund_recommend.py --sync-universe   # 新基写入 fund_universe.csv
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.advisor.fund_recommend import (
    FundRecommendResult,
    generate_fund_recommendations,
    render_recommend_markdown,
    save_recommendation,
)
from src.advisor.recommend_rules import enrich_candidate_pool
from src.analytics.screener import screen_funds
from src.collectors.fund_rank import fetch_all_ranks
from src.config_loader import CONFIG_DIR, load_fund_universe, load_strategy


def sync_to_fund_universe(recommendations: list[dict]) -> int:
    """将新推荐的买入基金追加到 fund_universe.csv（已存在则跳过）。"""
    path = CONFIG_DIR / "fund_universe.csv"
    existing = {r["fund_code"] for r in load_fund_universe()}
    added = 0
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8-sig").rstrip().splitlines()

    for r in recommendations:
        if r.get("action") not in ("buy", "add"):
            continue
        code = r["fund_code"]
        if code in existing:
            continue
        name = r.get("fund_name", code).replace(",", " ")
        theme = "宽基" if r.get("is_broad_index") else "推荐池"
        lines.append(f"{code},{name},{theme},medium,AI推荐-{date.today().isoformat()}")
        existing.add(code)
        added += 1

    if added:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description="全市场基金筛选与 AI 推荐")
    parser.add_argument("--no-cache", action="store_true", help="强制重新拉取排行")
    parser.add_argument("--no-ai", action="store_true", help="不调用 LLM")
    parser.add_argument("--budget", type=float, help="覆盖 strategy 中的 budget_cny")
    parser.add_argument(
        "--sync-universe",
        action="store_true",
        help="将新推荐的基金写入 fund_universe.csv",
    )
    args = parser.parse_args()

    strategy = load_strategy()
    rec_cfg = dict(strategy.get("recommendation") or {})
    if not rec_cfg.get("enabled", True):
        print("recommendation.enabled 为 false，已在 strategy.yaml 关闭")
        return 1

    if args.budget:
        rec_cfg["budget_cny"] = args.budget
        strategy = load_strategy()
        strategy["recommendation"] = {**strategy.get("recommendation", {}), **rec_cfg}

    fund_types = rec_cfg.get("fund_types") or ["混合型", "指数型"]
    print(f"正在拉取排行: {', '.join(fund_types)}（约需 30～60 秒）...")

    try:
        df = fetch_all_ranks(fund_types, use_cache=not args.no_cache)
    except Exception as e:
        print(f"拉取失败: {e}")
        return 1

    print(f"  共 {len(df)} 只基金（去重后）")
    screened = screen_funds(df, rec_cfg)
    screened = enrich_candidate_pool(df, screened, rec_cfg, strategy)
    print(f"  规则筛选后 {len(screened)} 只进入候选池（含主仓/宽基补全）")

    if args.no_ai:
        result = FundRecommendResult(
            summary="（未调用 AI，见下方候选 Top 10）",
            budget_cny=float(rec_cfg.get("budget_cny", 5000)),
            screened_count=len(screened),
            skipped=False,
        )
    else:
        print("正在调用 AI 生成推荐...")
        result = generate_fund_recommendations(screened, use_llm=True, strategy_override=strategy)
        if result.skipped:
            print(f"AI 跳过: {result.skip_reason}")

    md = render_recommend_markdown(result, screened)
    json_path, md_path = save_recommendation(result, md)
    print(f"\nJSON: {json_path}")
    print(f"报告: {md_path}")

    if args.sync_universe and result.recommendations:
        n = sync_to_fund_universe(result.recommendations)
        print(f"fund_universe.csv：新增 {n} 只基金")

    if result.rule_warnings:
        print("\n规则校验:")
        for w in result.rule_warnings:
            print(f"  - {w}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
