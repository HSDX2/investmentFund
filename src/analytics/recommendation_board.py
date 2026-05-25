"""推荐看板：基于真实资金流、情绪与基金数据生成带理由的推荐。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.analytics.portfolio import WatchlistItem
from src.collectors.capital_flow import DEFAULT_THEME_KEYWORDS, CapitalFlowSnapshot
from src.config_loader import ROOT

RECOMMEND_DIR = ROOT / "data" / "recommendations"


@dataclass
class ReasonItem:
    type: str  # flow | sentiment | performance | news | theme | weekly | sector
    label: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "label": self.label, "detail": self.detail}


@dataclass
class FundPick:
    fund_code: str
    fund_name: str
    action: str  # buy | add | hold | watch
    theme: str
    score: float
    reasons: list[ReasonItem] = field(default_factory=list)
    source: str = "daily"  # daily | weekly
    daily_growth_pct: float | None = None
    return_1y: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "action": self.action,
            "theme": self.theme,
            "score": round(self.score, 2),
            "reasons": [r.to_dict() for r in self.reasons],
            "source": self.source,
            "daily_growth_pct": self.daily_growth_pct,
            "return_1y": self.return_1y,
        }


@dataclass
class StockPick:
    name: str
    sector: str
    sector_net_yi: float
    sector_change_pct: float | None
    leader_change_pct: float | None
    flow_type: str
    score: float
    reasons: list[ReasonItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sector": self.sector,
            "sector_net_yi": self.sector_net_yi,
            "sector_change_pct": self.sector_change_pct,
            "leader_change_pct": self.leader_change_pct,
            "flow_type": self.flow_type,
            "score": round(self.score, 2),
            "reasons": [r.to_dict() for r in self.reasons],
        }


@dataclass
class RecommendationBoard:
    sentiment_score: float = 50.0
    sentiment_label: str = "中性"
    sentiment_summary: str = ""
    fund_picks: list[FundPick] = field(default_factory=list)
    stock_picks: list[StockPick] = field(default_factory=list)
    weekly_recommend_date: str | None = None
    data_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sentiment_score": self.sentiment_score,
            "sentiment_label": self.sentiment_label,
            "sentiment_summary": self.sentiment_summary,
            "fund_picks": [p.to_dict() for p in self.fund_picks],
            "stock_picks": [p.to_dict() for p in self.stock_picks],
            "weekly_recommend_date": self.weekly_recommend_date,
            "data_sources": self.data_sources,
        }


def _load_latest_weekly_recommend(max_age_days: int) -> dict[str, Any] | None:
    if not RECOMMEND_DIR.exists():
        return None
    files = sorted(RECOMMEND_DIR.glob("20*.json"), reverse=True)
    if not files:
        return None
    path = files[0]
    try:
        d = date.fromisoformat(path.stem)
    except ValueError:
        return None
    if date.today() - d > timedelta(days=max_age_days):
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_file_date"] = path.stem
        return data
    except json.JSONDecodeError:
        return None


def _theme_keywords(strategy: dict) -> dict[str, list[str]]:
    cfg = strategy.get("market_flow") or {}
    return {**DEFAULT_THEME_KEYWORDS, **(cfg.get("theme_keywords") or {})}


def _match_fund_to_sectors(
    fund_name: str,
    theme: str,
    top_inflows: list[dict],
    theme_keywords: dict[str, list[str]],
) -> list[dict]:
    kws: set[str] = {theme} if theme else set()
    for kw in theme_keywords.get(theme, DEFAULT_THEME_KEYWORDS.get(theme, [])):
        kws.add(kw)
    for kw in DEFAULT_THEME_KEYWORDS.get(theme, []):
        kws.add(kw)

    matched: list[dict] = []
    for sector in top_inflows:
        name = sector.get("name", "")
        if any(kw in fund_name or kw in name for kw in kws if kw):
            matched.append(sector)
    return matched


def _news_for_theme(theme: str, news_digest: list[dict], theme_keywords: dict[str, list[str]]) -> list[dict]:
    kws = {theme, *theme_keywords.get(theme, DEFAULT_THEME_KEYWORDS.get(theme, []))}
    out: list[dict] = []
    for item in news_digest:
        blob = f"{item.get('keyword','')} {item.get('title','')} {item.get('summary','')}"
        if any(kw and kw in blob for kw in kws):
            out.append(item)
    return out[:2]


def _build_stock_picks(
    capital_flow: CapitalFlowSnapshot | None,
    flow_trends: dict[str, Any],
    max_n: int,
) -> list[StockPick]:
    if not capital_flow or capital_flow.error:
        return []

    picks: list[StockPick] = []
    seen: set[str] = set()

    for item in (capital_flow.top_inflows or [])[: max_n * 2]:
        stock = getattr(item, "leader_stock", None) or (item.to_dict() if hasattr(item, "to_dict") else item).get("leader_stock")
        if isinstance(item, dict):
            d = item
            stock = d.get("leader_stock")
            name = d.get("name", "")
            net = float(d.get("net_inflow_yi") or 0)
            chg = d.get("change_pct")
            lchg = d.get("leader_change_pct")
            ftype = d.get("flow_type", "industry")
        else:
            d = item.to_dict()
            stock = item.leader_stock
            name = item.name
            net = item.net_inflow_yi
            chg = item.change_pct
            lchg = item.leader_change_pct
            ftype = item.flow_type

        if not stock or stock in seen:
            continue
        seen.add(stock)

        reasons = [
            ReasonItem(
                "flow",
                "板块主力净流入",
                f"{name} 今日净流入 {net:+.2f} 亿元，涨幅 {chg if chg is not None else '—'}%",
            ),
            ReasonItem(
                "sector",
                "板块龙头",
                f"{stock} 为 {name} 领涨股，涨幅 {lchg if lchg is not None else '—'}%",
            ),
        ]

        hot = next((h for h in flow_trends.get("hot_sectors", []) if h.get("name") == name), None)
        if hot:
            reasons.append(
                ReasonItem(
                    "flow",
                    "近阶段持续吸金",
                    f"近 {flow_trends.get('lookback_days', 30)} 日累计净流入约 {hot.get('cumulative_net_yi')} 亿",
                )
            )

        score = net * 0.4 + (lchg or 0) * 2 + (chg or 0)
        picks.append(
            StockPick(
                name=stock,
                sector=name,
                sector_net_yi=net,
                sector_change_pct=chg,
                leader_change_pct=lchg,
                flow_type=ftype,
                score=score,
                reasons=reasons,
            )
        )
        if len(picks) >= max_n:
            break

    picks.sort(key=lambda x: x.score, reverse=True)
    return picks


def _build_fund_picks_from_weekly(
    weekly: dict[str, Any],
    capital_flow: CapitalFlowSnapshot | None,
    flow_trends: dict[str, Any],
    news_digest: list[dict],
    theme_keywords: dict[str, list[str]],
) -> list[FundPick]:
    picks: list[FundPick] = []
    top_inflows = [
        (x.to_dict() if hasattr(x, "to_dict") else x)
        for x in (capital_flow.top_inflows if capital_flow else [])
    ]

    for rec in weekly.get("recommendations") or []:
        code = str(rec.get("fund_code", "")).zfill(6)
        theme = "宽基" if rec.get("is_broad_index") else "推荐池"
        reasons: list[ReasonItem] = [
            ReasonItem("weekly", "每周选基", rec.get("reason") or "AI 全市场筛选推荐")
        ]

        matched = _match_fund_to_sectors(rec.get("fund_name", ""), theme, top_inflows, theme_keywords)
        for sec in matched[:2]:
            reasons.append(
                ReasonItem(
                    "flow",
                    "资金面对齐",
                    f"{sec.get('name')} 净流入 {sec.get('net_inflow_yi'):+.2f} 亿",
                )
            )

        if flow_trends.get("sentiment_label"):
            reasons.append(
                ReasonItem(
                    "sentiment",
                    "市场情绪",
                    f"{flow_trends.get('sentiment_label')}（{flow_trends.get('sentiment_score')} 分），"
                    f"北向近5日 {flow_trends.get('northbound_sum_5d_yi', 0):+.2f} 亿",
                )
            )

        picks.append(
            FundPick(
                fund_code=code,
                fund_name=str(rec.get("fund_name") or code),
                action=str(rec.get("action") or "buy"),
                theme=theme,
                score=float(rec.get("confidence") or 0.7) * 100,
                reasons=reasons,
                source="weekly",
                return_1y=rec.get("return_1y"),
            )
        )
    return picks


def _build_fund_picks_daily(
    watchlist: list[WatchlistItem],
    universe: list[dict[str, str]],
    positions: list[dict[str, str]],
    capital_flow: CapitalFlowSnapshot | None,
    flow_trends: dict[str, Any],
    news_digest: list[dict],
    theme_keywords: dict[str, list[str]],
    max_n: int,
) -> list[FundPick]:
    top_inflows = [
        (x.to_dict() if hasattr(x, "to_dict") else x)
        for x in (capital_flow.top_inflows if capital_flow else [])
    ]
    held = {p["fund_code"] for p in positions}

    candidates: dict[str, dict[str, Any]] = {}
    for row in universe:
        code = row["fund_code"]
        candidates[code] = {
            "fund_code": code,
            "fund_name": row.get("fund_name", code),
            "theme": row.get("theme", "未分类"),
            "daily_growth_pct": None,
            "is_held": code in held,
        }
    for w in watchlist:
        candidates[w.fund_code] = {
            "fund_code": w.fund_code,
            "fund_name": w.fund_name,
            "theme": w.theme,
            "daily_growth_pct": w.daily_growth_pct,
            "is_held": w.fund_code in held,
        }

    picks: list[FundPick] = []
    for c in candidates.values():
        theme = c.get("theme") or "未分类"
        if theme in ("未分类",):
            continue

        matched = _match_fund_to_sectors(c["fund_name"], theme, top_inflows, theme_keywords)
        flow_score = sum(float(s.get("net_inflow_yi") or 0) for s in matched)
        if flow_score <= 0 and not matched:
            continue

        reasons: list[ReasonItem] = []
        for sec in matched[:2]:
            reasons.append(
                ReasonItem(
                    "flow",
                    "板块资金流入",
                    f"{sec.get('name')} 净流入 {sec.get('net_inflow_yi'):+.2f} 亿，"
                    f"涨 {sec.get('change_pct') if sec.get('change_pct') is not None else '—'}%",
                )
            )

        reasons.append(
            ReasonItem(
                "sentiment",
                "市场情绪",
                f"{flow_trends.get('sentiment_label')}（{flow_trends.get('sentiment_score')}），"
                f"主力近5日方向均值 {flow_trends.get('direction_avg_5d', 0):+.2f}",
            )
        )

        news_hits = _news_for_theme(theme, news_digest, theme_keywords)
        for n in news_hits:
            reasons.append(
                ReasonItem(
                    "news",
                    "相关要闻",
                    (n.get("summary") or n.get("title") or "")[:80],
                )
            )

        if c.get("is_held"):
            reasons.append(ReasonItem("theme", "已有持仓", f"当前持仓主题「{theme}」，资金面向好可考虑持有或小幅加仓"))
            action = "hold"
        else:
            reasons.append(ReasonItem("theme", "主题匹配", f"关注主题「{theme}」与今日主力流入板块一致"))
            action = "watch"

        daily = c.get("daily_growth_pct")
        if daily is not None:
            reasons.append(
                ReasonItem("performance", "净值表现", f"最新日涨跌 {daily:+.2f}%")
            )

        score = flow_score + (daily or 0) * 3 + (10 if c.get("is_held") else 0)
        picks.append(
            FundPick(
                fund_code=c["fund_code"],
                fund_name=c["fund_name"],
                action=action,
                theme=theme,
                score=score,
                reasons=reasons,
                source="daily",
                daily_growth_pct=daily,
            )
        )

    picks.sort(key=lambda x: x.score, reverse=True)
    return picks[:max_n]


def build_recommendation_board(
    strategy: dict,
    watchlist: list[WatchlistItem],
    universe: list[dict[str, str]],
    positions: list[dict[str, str]],
    capital_flow: CapitalFlowSnapshot | None,
    flow_trends: dict[str, Any],
    news_digest: list[dict] | None = None,
) -> RecommendationBoard:
    cfg = strategy.get("recommendation_board") or {}
    if not cfg.get("enabled", True):
        return RecommendationBoard(sentiment_summary="推荐看板已禁用")

    max_funds = int(cfg.get("max_fund_picks", 5))
    max_stocks = int(cfg.get("max_stock_picks", 8))
    weekly_days = int(cfg.get("use_weekly_recommend_days", 14))
    theme_keywords = _theme_keywords(strategy)
    news_digest = news_digest or []

    sources: list[str] = []
    if capital_flow and capital_flow.data_source:
        sources.append(capital_flow.data_source)
    sources.append("capital_flow_history")

    sentiment_score = float(flow_trends.get("sentiment_score") or 50)
    sentiment_label = str(flow_trends.get("sentiment_label") or "中性")

    nb5 = flow_trends.get("northbound_sum_5d_yi")
    nb10 = flow_trends.get("northbound_sum_10d_yi")
    hot = flow_trends.get("hot_sectors") or []
    hot_txt = "、".join(f"{h['name']}({h['cumulative_net_yi']}亿)" for h in hot[:3]) or "—"

    overall = capital_flow.overall_label if capital_flow else "—"
    sentiment_summary = (
        f"今日主力{overall}；情绪指数 {sentiment_score}（{sentiment_label}）。"
        f"北向近5日/10日累计 {nb5:+.2f}/{nb10:+.2f} 亿元。"
        f"阶段吸金板块：{hot_txt}。"
    )

    weekly = _load_latest_weekly_recommend(weekly_days)
    weekly_date = weekly.get("_file_date") if weekly else None

    fund_picks: list[FundPick] = []
    if weekly and weekly.get("recommendations"):
        fund_picks = _build_fund_picks_from_weekly(
            weekly, capital_flow, flow_trends, news_digest, theme_keywords
        )
        sources.append(f"weekly_recommend:{weekly_date}")
    if len(fund_picks) < max_funds:
        daily_picks = _build_fund_picks_daily(
            watchlist,
            universe,
            positions,
            capital_flow,
            flow_trends,
            news_digest,
            theme_keywords,
            max_funds,
        )
        seen = {p.fund_code for p in fund_picks}
        for p in daily_picks:
            if p.fund_code not in seen:
                fund_picks.append(p)
                seen.add(p.fund_code)
            if len(fund_picks) >= max_funds:
                break

    stock_picks = _build_stock_picks(capital_flow, flow_trends, max_stocks)
    if stock_picks:
        sources.append("sector_leader_stocks")

    return RecommendationBoard(
        sentiment_score=sentiment_score,
        sentiment_label=sentiment_label,
        sentiment_summary=sentiment_summary,
        fund_picks=fund_picks[:max_funds],
        stock_picks=stock_picks,
        weekly_recommend_date=weekly_date,
        data_sources=sources,
    )
