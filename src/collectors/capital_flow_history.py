"""主力资金流历史持久化与趋势分析。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import akshare as ak
import pandas as pd

from src.collectors.capital_flow import CapitalFlowSnapshot
from src.config_loader import ROOT

FLOW_DIR = ROOT / "data" / "capital_flow"


def save_flow_snapshot(snapshot: CapitalFlowSnapshot) -> Path:
    """按交易日落盘快照，供历史趋势使用。"""
    FLOW_DIR.mkdir(parents=True, exist_ok=True)
    d = snapshot.trade_date or date.today().isoformat()
    path = FLOW_DIR / f"{d}.json"
    path.write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_flow_history(days: int = 30) -> list[dict[str, Any]]:
    if not FLOW_DIR.exists():
        return []
    cutoff = date.today() - timedelta(days=days)
    out: list[dict[str, Any]] = []
    for p in sorted(FLOW_DIR.glob("20*.json")):
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if d < cutoff:
            continue
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(out, key=lambda x: x.get("trade_date", ""))


def fetch_northbound_history(days: int = 30) -> list[dict[str, Any]]:
    """拉取北向资金历史（亿元），过滤无效行。"""
    try:
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
    except Exception:
        return []

    if df is None or df.empty:
        return []

    work = df.copy()
    work["日期"] = pd.to_datetime(work["日期"])
    net_col = "当日成交净买额"
    if net_col not in work.columns:
        return []

    work[net_col] = pd.to_numeric(work[net_col], errors="coerce")
    work = work.dropna(subset=[net_col])
    cutoff = pd.Timestamp(date.today() - timedelta(days=days))
    work = work[work["日期"] >= cutoff].sort_values("日期")

    out: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        hs300 = row.get("沪深300")
        hs300_pct = row.get("沪深300-涨跌幅")
        out.append(
            {
                "date": row["日期"].strftime("%Y-%m-%d"),
                "net_yi": round(float(row[net_col]), 2),
                "hs300": round(float(hs300), 2) if pd.notna(hs300) else None,
                "hs300_pct": round(float(hs300_pct), 2) if pd.notna(hs300_pct) else None,
            }
        )
    return out


def _direction_score(direction: str) -> int:
    return {"inflow": 1, "neutral": 0, "outflow": -1}.get(direction or "neutral", 0)


def build_flow_trends(
    history: list[dict[str, Any]],
    northbound_hist: list[dict[str, Any]],
    *,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """汇总多日主力方向、北向累计与板块热度变化。"""
    daily_series: list[dict[str, Any]] = []
    for snap in history[-lookback_days:]:
        nb = snap.get("northbound") or {}
        top1 = (snap.get("top_inflows") or [{}])[0]
        daily_series.append(
            {
                "date": snap.get("trade_date"),
                "overall_direction": snap.get("overall_direction", "neutral"),
                "overall_label": snap.get("overall_label", ""),
                "northbound_net_yi": nb.get("total_net_yi"),
                "top_sector": top1.get("name"),
                "top_sector_net_yi": top1.get("net_inflow_yi"),
            }
        )

    dir_scores = [_direction_score(d.get("overall_direction")) for d in daily_series]
    recent_5 = dir_scores[-5:] if dir_scores else []
    recent_10 = dir_scores[-10:] if dir_scores else []

    nb_recent = northbound_hist[-5:] if northbound_hist else []
    nb_sum_5d = round(sum(x.get("net_yi", 0) for x in nb_recent), 2)
    nb_sum_10d = round(
        sum(x.get("net_yi", 0) for x in (northbound_hist[-10:] if northbound_hist else [])),
        2,
    )

    # 统计近 N 日板块出现频次（热度）
    sector_hits: dict[str, float] = {}
    for snap in history[-lookback_days:]:
        for item in snap.get("top_inflows") or []:
            name = item.get("name")
            if not name:
                continue
            sector_hits[name] = sector_hits.get(name, 0) + float(item.get("net_inflow_yi") or 0)

    hot_sectors = sorted(sector_hits.items(), key=lambda x: x[1], reverse=True)[:5]
    hot_sector_list = [
        {"name": name, "cumulative_net_yi": round(net, 2)} for name, net in hot_sectors
    ]

    sentiment_score = 50.0
    if recent_5:
        sentiment_score += sum(recent_5) / len(recent_5) * 12
    if nb_sum_5d:
        sentiment_score += max(-15, min(15, nb_sum_5d / 3))
    sentiment_score = max(0, min(100, round(sentiment_score, 1)))

    if sentiment_score >= 65:
        sentiment_label = "偏乐观"
    elif sentiment_score >= 45:
        sentiment_label = "中性"
    elif sentiment_score >= 30:
        sentiment_label = "偏谨慎"
    else:
        sentiment_label = "偏悲观"

    return {
        "lookback_days": lookback_days,
        "snapshot_days": len(daily_series),
        "daily_series": daily_series,
        "northbound_series": northbound_hist,
        "northbound_sum_5d_yi": nb_sum_5d,
        "northbound_sum_10d_yi": nb_sum_10d,
        "direction_avg_5d": round(sum(recent_5) / len(recent_5), 2) if recent_5 else 0,
        "direction_avg_10d": round(sum(recent_10) / len(recent_10), 2) if recent_10 else 0,
        "hot_sectors": hot_sector_list,
        "sentiment_score": sentiment_score,
        "sentiment_label": sentiment_label,
    }
