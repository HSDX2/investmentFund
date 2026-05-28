"""构建供 LLM 使用的结构化上下文（数字由程序计算）。"""

from __future__ import annotations

from dataclasses import asdict

from src.analytics.portfolio import PortfolioSummary, WatchlistItem
from src.risk.rules import RuleSignal


def theme_map(universe: list[dict[str, str]]) -> dict[str, str]:
    return {row["fund_code"]: row.get("theme", "未分类") for row in universe}


def build_advisor_context(
    report_date: str,
    data_as_of: str,
    portfolio: PortfolioSummary,
    watchlist: list[WatchlistItem],
    strategy: dict,
    rule_signals: list[RuleSignal],
    fund_universe: list[dict[str, str]],
    positions_cfg: list[dict[str, str]],
    news_digest: list[dict] | None = None,
    trend_observation: dict | None = None,
) -> dict:
    benchmark = None
    if portfolio.benchmark:
        b = portfolio.benchmark
        benchmark = {
            "index_code": strategy.get("benchmark", {}).get("index_code"),
            "name": b.name,
            "trade_date": str(b.trade_date),
            "close": b.close,
            "daily_change_pct": b.daily_change_pct,
        }

    return {
        "date": report_date,
        "data_as_of": data_as_of,
        "trading_mode": strategy.get("trading", {}).get("mode", "advise_only"),
        "investor": strategy.get("investor", {}),
        "allocation_limits": strategy.get("allocation", {}),
        "signal_thresholds": strategy.get("signals", {}),
        "portfolio": {
            "total_market_value": portfolio.total_market_value,
            "total_cost_value": portfolio.total_cost_value,
            "total_unrealized_pnl": portfolio.total_unrealized_pnl,
            "total_unrealized_pnl_pct": portfolio.total_unrealized_pnl_pct,
            "positions": [asdict(p) for p in portfolio.positions],
        },
        "watchlist": [asdict(w) for w in watchlist],
        "fund_universe": fund_universe,
        "positions_meta": positions_cfg,
        "rule_signals": [s.to_dict() for s in rule_signals],
        "benchmark": benchmark,
        "news_digest": news_digest or [],
        "trend_observation": trend_observation,
    }
