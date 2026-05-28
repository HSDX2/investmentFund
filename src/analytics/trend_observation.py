"""基金级趋势观察（阶段涨跌 + 回撤/反弹），供 AI 参考，不自动下单。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd

from src.analytics.portfolio import PortfolioSummary
from src.collectors.index_benchmark import _load_cache, _normalize_index_code
from src.collectors.nav import CACHE_DIR as NAV_CACHE_DIR, _load_cache as _load_nav_cache

TREND_LABELS = {
    "uptrend_intact": "上升趋势未破（大涨后小回）",
    "uptrend_pullback": "上升趋势中回调加深",
    "downtrend_intact": "下降趋势未转强（大跌后小弹）",
    "downtrend_bounce": "下降趋势中反弹加大",
    "neutral": "震荡/方向不明",
    "insufficient_data": "历史数据不足",
}


def _nav_series(fund_code: str, lookback: int) -> list[dict]:
    cache_file = NAV_CACHE_DIR / f"{fund_code}.csv"
    if not cache_file.exists():
        return []
    df = _load_nav_cache(cache_file)
    if df is None or df.empty:
        return []
    cutoff = pd.Timestamp(date.today() - timedelta(days=lookback))
    df = df[df["净值日期"] >= cutoff].sort_values("净值日期")
    return [
        {
            "date": row["净值日期"].strftime("%Y-%m-%d"),
            "nav": float(row["单位净值"]),
        }
        for _, row in df.iterrows()
        if pd.notna(row["单位净值"])
    ]


def _index_series(index_code: str, lookback: int) -> list[dict]:
    symbol = _normalize_index_code(index_code)
    df = _load_cache(symbol)
    if df is None or df.empty:
        return []
    cutoff = pd.Timestamp(date.today() - timedelta(days=lookback))
    df = df[df["日期"] >= cutoff].sort_values("日期")
    return [
        {
            "date": row["日期"].strftime("%Y-%m-%d"),
            "nav": float(row["收盘"]),
        }
        for _, row in df.iterrows()
    ]


def _analyze_series(
    name: str,
    code: str,
    points: list[dict],
    *,
    big_move_pct: float,
    small_correction_pct: float,
    lookback_days: int,
) -> dict[str, Any]:
    if len(points) < 10:
        return {
            "name": name,
            "code": code,
            "trend": "insufficient_data",
            "trend_label": TREND_LABELS["insufficient_data"],
            "hint": "净值历史不足，暂不判断趋势",
            "lookback_days": lookback_days,
            "data_points": len(points),
        }

    navs = [p["nav"] for p in points]
    first, last = navs[0], navs[-1]
    peak = max(navs)
    trough = min(navs)
    period_return_pct = (last - first) / first * 100 if first > 0 else 0.0
    drawdown_from_peak_pct = (last - peak) / peak * 100 if peak > 0 else 0.0
    bounce_from_trough_pct = (last - trough) / trough * 100 if trough > 0 else 0.0

    trend = "neutral"
    hint = "阶段涨跌不大，以规则与止损为主，不宜频繁换基。"

    if period_return_pct >= big_move_pct:
        if drawdown_from_peak_pct >= -small_correction_pct:
            trend = "uptrend_intact"
            hint = (
                f"近{lookback_days}日涨约{period_return_pct:.1f}%，"
                f"自高点仅回落{abs(drawdown_from_peak_pct):.1f}%（小回），"
                "趋势心法：上升未破，倾向持有或小批加仓，不因单日下跌恐慌换基。"
            )
        else:
            trend = "uptrend_pullback"
            hint = (
                f"近{lookback_days}日仍涨{period_return_pct:.1f}%，"
                f"但自高点已回落{abs(drawdown_from_peak_pct):.1f}%，"
                "回调加深，宜观察是否转弱，暂不建议追涨。"
            )
    elif period_return_pct <= -big_move_pct:
        if bounce_from_trough_pct <= small_correction_pct:
            trend = "downtrend_intact"
            hint = (
                f"近{lookback_days}日跌约{abs(period_return_pct):.1f}%，"
                f"自低点仅反弹{bounce_from_trough_pct:.1f}%（小弹），"
                "趋势心法：下降未转强，不宜急于抄底或换入同主题，优先风控。"
            )
        else:
            trend = "downtrend_bounce"
            hint = (
                f"近{lookback_days}日仍跌{abs(period_return_pct):.1f}%，"
                f"但自低点已反弹{bounce_from_trough_pct:.1f}%，"
                "或有修复，需结合规则止损与新闻，勿情绪化追反弹。"
            )

    return {
        "name": name,
        "code": code,
        "trend": trend,
        "trend_label": TREND_LABELS.get(trend, trend),
        "hint": hint,
        "lookback_days": lookback_days,
        "data_points": len(points),
        "period_return_pct": round(period_return_pct, 2),
        "drawdown_from_peak_pct": round(drawdown_from_peak_pct, 2),
        "bounce_from_trough_pct": round(bounce_from_trough_pct, 2),
    }


def build_trend_observation(
    strategy: dict,
    portfolio: PortfolioSummary,
    positions_cfg: list[dict[str, str]],
) -> dict[str, Any] | None:
    cfg = strategy.get("trend_observation") or {}
    if not cfg.get("enabled", True):
        return None

    lookback = int(cfg.get("lookback_days", 90))
    big_move = float(cfg.get("big_move_pct", 12))
    small_corr = float(cfg.get("small_correction_pct", 6))

    items: list[dict[str, Any]] = []
    for pos in portfolio.positions:
        code = pos.fund_code
        series = _nav_series(code, lookback)
        items.append(
            _analyze_series(
                pos.fund_name,
                code,
                series,
                big_move_pct=big_move,
                small_correction_pct=small_corr,
                lookback_days=lookback,
            )
        )

    benchmark_item = None
    index_code = strategy.get("benchmark", {}).get("index_code", "000300.SH")
    if portfolio.benchmark:
        idx_series = _index_series(index_code, lookback)
        benchmark_item = _analyze_series(
            portfolio.benchmark.name,
            index_code,
            idx_series,
            big_move_pct=big_move,
            small_correction_pct=small_corr,
            lookback_days=lookback,
        )

    philosophy = str(cfg.get("philosophy") or "").strip()
    ai_guidance = {
        "prefer_hold_on_uptrend_intact": cfg.get("prefer_hold_on_uptrend", True),
        "avoid_chase_on_downtrend_intact": cfg.get("avoid_chase_on_downtrend", True),
        "do_not_day_trade": True,
        "note": "场外基金净值 T+1，以下仅为阶段趋势参考，非个股 K 线交易信号",
    }

    return {
        "lookback_days": lookback,
        "big_move_pct": big_move,
        "small_correction_pct": small_corr,
        "philosophy": philosophy,
        "ai_guidance": ai_guidance,
        "holdings": items,
        "benchmark": benchmark_item,
    }
