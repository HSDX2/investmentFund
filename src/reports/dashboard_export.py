"""导出 Dashboard 用 JSON 快照到 docs/data/。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.advisor.advisor import AdviceResult
from src.advisor.market_outlook import MarketOutlook
from src.analytics.portfolio import PortfolioSummary, WatchlistItem
from src.analytics.recommendation_board import RecommendationBoard
from src.collectors.capital_flow import CapitalFlowSnapshot
from src.collectors.index_benchmark import _load_cache, _normalize_index_code
from src.collectors.nav import CACHE_DIR as NAV_CACHE_DIR, _load_cache as _load_nav_cache
from src.config_loader import ROOT
from src.notify.batch_state import load_batch_state

DOCS_DATA = ROOT / "docs" / "data"
LOOKBACK_DAYS = 90


def _nav_history_series(fund_code: str, lookback: int) -> list[dict]:
    cache_file = NAV_CACHE_DIR / f"{fund_code}.csv"
    if not cache_file.exists():
        return []
    df = _load_nav_cache(cache_file)
    if df is None or df.empty:
        return []
    cutoff = pd.Timestamp(date.today() - timedelta(days=lookback))
    df = df[df["净值日期"] >= cutoff]
    out: list[dict] = []
    for _, row in df.iterrows():
        pct = row.get("日增长率")
        out.append(
            {
                "date": row["净值日期"].strftime("%Y-%m-%d"),
                "nav": round(float(row["单位净值"]), 4),
                "pct": round(float(pct), 2) if pd.notna(pct) else None,
            }
        )
    return out


def _index_history_series(index_code: str, lookback: int) -> list[dict]:
    symbol = _normalize_index_code(index_code)
    df = _load_cache(symbol)
    if df is None or df.empty:
        return []
    cutoff = pd.Timestamp(date.today() - timedelta(days=lookback))
    df = df[df["日期"] >= cutoff]
    return [
        {
            "date": row["日期"].strftime("%Y-%m-%d"),
            "close": round(float(row["收盘"]), 2),
        }
        for _, row in df.iterrows()
    ]


def _normalized_curve(points: list[dict], value_key: str) -> list[dict]:
    if not points:
        return []
    base = points[0][value_key]
    if not base:
        return []
    return [
        {
            "date": p["date"],
            "value": round(p[value_key] / base * 100, 2),
        }
        for p in points
        if p.get(value_key)
    ]


def _portfolio_value_series(
    positions: list[dict],
    lookback: int,
) -> list[dict]:
    """按固定份额估算账户总市值曲线。"""
    series_map: dict[str, float] = {}
    for pos in positions:
        code = pos["fund_code"]
        shares = float(pos["shares"])
        hist = _nav_history_series(code, lookback)
        for pt in hist:
            d = pt["date"]
            series_map[d] = series_map.get(d, 0.0) + shares * pt["nav"]
    return [
        {"date": d, "value": round(v, 2)}
        for d, v in sorted(series_map.items())
    ]


def _portfolio_return_curve(value_series: list[dict]) -> list[dict]:
    if not value_series:
        return []
    base = value_series[0]["value"]
    if base <= 0:
        return []
    return [
        {"date": p["date"], "value": round(p["value"] / base * 100, 2)}
        for p in value_series
    ]


def _benchmark_dict(benchmark) -> dict | None:
    if not benchmark:
        return None
    return {
        "index_code": benchmark.index_code,
        "name": benchmark.name,
        "trade_date": str(benchmark.trade_date),
        "close": benchmark.close,
        "daily_change_pct": benchmark.daily_change_pct,
        "data_source": getattr(benchmark, "data_source", ""),
    }


def _list_report_dates() -> list[str]:
    reports_dir = ROOT / "docs" / "reports"
    dates: list[str] = []
    if not reports_dir.exists():
        return dates
    for p in reports_dir.glob("20*.html"):
        stem = p.stem
        if stem.startswith("fund-recommend-"):
            continue
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-":
            dates.append(stem)
    return sorted(dates, reverse=True)


def build_dashboard_payload(
    report_date: str,
    data_as_of: str,
    portfolio: PortfolioSummary,
    watchlist: list[WatchlistItem],
    advice: AdviceResult | None,
    positions_cfg: list[dict[str, str]],
    strategy: dict,
    *,
    capital_flow: CapitalFlowSnapshot | None = None,
    market_outlook=None,
    flow_trends: dict | None = None,
    recommendation_board: RecommendationBoard | None = None,
    lookback_days: int = LOOKBACK_DAYS,
) -> dict:
    index_code = strategy.get("benchmark", {}).get("index_code", "000300.SH")
    codes = list({p.fund_code for p in portfolio.positions})
    for w in watchlist:
        if w.fund_code not in codes:
            codes.append(w.fund_code)

    nav_series = {code: _nav_history_series(code, lookback_days) for code in codes}
    fund_curves = {
        code: _normalized_curve(nav_series[code], "nav")
        for code in codes
        if nav_series.get(code)
    }

    index_raw = _index_history_series(index_code, lookback_days)
    index_curve = _normalized_curve(
        [{"date": p["date"], "nav": p["close"]} for p in index_raw],
        "nav",
    )
    portfolio_values = _portfolio_value_series(positions_cfg, lookback_days)
    portfolio_curve = _portfolio_return_curve(portfolio_values)

    batch = load_batch_state()
    advice_dict = advice.to_dict() if advice else None

    portfolio_daily_pct = None
    if portfolio.positions:
        acc = sum(
            (p.weight_pct / 100) * (p.daily_growth_pct or 0)
            for p in portfolio.positions
            if p.daily_growth_pct is not None
        )
        portfolio_daily_pct = round(acc, 2)

    b = portfolio.benchmark
    bench_diff = None
    if b and b.daily_change_pct is not None and portfolio_daily_pct is not None:
        bench_diff = round(portfolio_daily_pct - b.daily_change_pct, 2)

    return {
        "date": report_date,
        "data_as_of": data_as_of,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "portfolio": {
            "total_market_value": portfolio.total_market_value,
            "total_cost_value": portfolio.total_cost_value,
            "total_unrealized_pnl": portfolio.total_unrealized_pnl,
            "total_unrealized_pnl_pct": portfolio.total_unrealized_pnl_pct,
            "estimated_daily_pct": portfolio_daily_pct,
            "vs_benchmark_daily_pct": bench_diff,
            "positions": [asdict(p) for p in portfolio.positions],
        },
        "benchmark": _benchmark_dict(portfolio.benchmark),
        "watchlist": [asdict(w) for w in watchlist],
        "advice": advice_dict,
        "market_flow": capital_flow.to_dict() if capital_flow else None,
        "market_outlook": (
            market_outlook.to_dict()
            if isinstance(market_outlook, MarketOutlook)
            else market_outlook
        ),
        "flow_trends": flow_trends,
        "recommendation_board": (
            recommendation_board.to_dict()
            if isinstance(recommendation_board, RecommendationBoard)
            else recommendation_board
        ),
        "charts": {
            "lookback_days": lookback_days,
            "fund_return_indexed": fund_curves,
            "portfolio_return_indexed": portfolio_curve,
            "portfolio_market_value": portfolio_values,
            "benchmark_return_indexed": index_curve,
            "benchmark_raw": index_raw,
        },
        "batch_state": batch,
        "strategy_summary": {
            "stop_loss_ratio": strategy.get("signals", {}).get("stop_loss_ratio"),
            "take_profit_ratio": strategy.get("signals", {}).get("take_profit_ratio"),
            "relax_caps_below": strategy.get("allocation", {}).get(
                "relax_caps_when_value_below"
            ),
            "benchmark_index": index_code,
        },
        "report_dates": _list_report_dates(),
    }


def export_dashboard_json(payload: dict, report_date: str | None = None) -> tuple[Path, Path]:
    """写入 docs/data/YYYY-MM-DD.json 与 latest.json。"""
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    d = report_date or payload.get("date") or date.today().isoformat()
    dated_path = DOCS_DATA / f"{d}.json"
    latest_path = DOCS_DATA / "latest.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    dated_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")

    manifest = {
        "updated_at": payload.get("generated_at"),
        "latest": d,
        "dates": sorted(
            {p.stem for p in DOCS_DATA.glob("20*.json") if p.stem != "manifest"},
            reverse=True,
        ),
    }
    (DOCS_DATA / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dated_path, latest_path
