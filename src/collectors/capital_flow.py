"""A 股主力资金流向（行业/概念/北向），供面板与 AI 方向分析。"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import akshare as ak
import pandas as pd

NORTHBOUND_DISCLOSURE_NOTE = (
    "北向资金每日「成交净买额」自 2024-08-19 起交易所已暂停披露，"
    "第三方接口（含 AkShare/东方财富）返回 0 或空值属正常，不代表当日无交易。"
    "可参考下方 A 股行业/概念主力资金与南向资金。"
)

# AkShare 历史接口最后有效日期（之后官方不再披露日度净买额）
NORTHBOUND_HIST_END = "2024-08-16"

DEFAULT_THEME_KEYWORDS: dict[str, list[str]] = {
    "人工智能": ["人工智能", "AI", "半导体", "芯片", "算力", "机器人"],
    "创新药": ["创新药", "医药", "生物", "医疗", "制药"],
    "纳斯达克": ["纳斯达克", "美股", "QDII"],
    "宽基": ["沪深300", "中证500", "上证50", "红利", "A500"],
}


@dataclass
class SectorFlowItem:
    name: str
    net_inflow_yi: float
    change_pct: float | None
    flow_type: str  # industry | concept
    inflow_yi: float | None = None
    outflow_yi: float | None = None
    leader_stock: str | None = None
    leader_change_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NorthboundFlow:
    trade_date: str
    sh_net_yi: float | None
    sz_net_yi: float | None
    total_net_yi: float | None
    direction: str  # inflow | outflow | neutral | unavailable
    disclosed: bool = True
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SouthboundFlow:
    trade_date: str
    sh_net_yi: float | None
    sz_net_yi: float | None
    total_net_yi: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapitalFlowSnapshot:
    trade_date: str = ""
    overall_direction: str = "neutral"  # inflow | outflow | neutral
    overall_label: str = "中性"
    northbound: NorthboundFlow | None = None
    southbound: SouthboundFlow | None = None
    top_inflows: list[SectorFlowItem] = field(default_factory=list)
    top_outflows: list[SectorFlowItem] = field(default_factory=list)
    theme_relevant: list[SectorFlowItem] = field(default_factory=list)
    data_source: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "overall_direction": self.overall_direction,
            "overall_label": self.overall_label,
            "northbound": self.northbound.to_dict() if self.northbound else None,
            "southbound": self.southbound.to_dict() if self.southbound else None,
            "top_inflows": [x.to_dict() for x in self.top_inflows],
            "top_outflows": [x.to_dict() for x in self.top_outflows],
            "theme_relevant": [x.to_dict() for x in self.theme_relevant],
            "data_source": self.data_source,
            "error": self.error,
        }


def _direction_from_net(net_yi: float, threshold: float = 5.0) -> str:
    if net_yi >= threshold:
        return "inflow"
    if net_yi <= -threshold:
        return "outflow"
    return "neutral"


def _direction_label(direction: str) -> str:
    return {"inflow": "净流入", "outflow": "净流出", "neutral": "中性"}.get(
        direction, "中性"
    )


def _parse_sector_df(
    df: pd.DataFrame, flow_type: str, top_n: int
) -> tuple[list[SectorFlowItem], list[SectorFlowItem]]:
    if df is None or df.empty or "净额" not in df.columns:
        return [], []

    work = df.copy()
    work["净额"] = pd.to_numeric(work["净额"], errors="coerce")
    work = work.dropna(subset=["净额"])
    name_col = "行业" if "行业" in work.columns else work.columns[1]
    pct_col = next((c for c in work.columns if "涨跌幅" in str(c) and "领涨" not in str(c)), None)
    leader_col = "领涨股" if "领涨股" in work.columns else None
    leader_pct_col = next(
        (c for c in work.columns if "领涨股" in str(c) and "涨跌幅" in str(c)),
        None,
    )

    items: list[SectorFlowItem] = []
    for _, row in work.iterrows():
        inflow = row.get("流入资金")
        outflow = row.get("流出资金")
        leader = str(row[leader_col]).strip() if leader_col and pd.notna(row.get(leader_col)) else None
        leader_pct = None
        if leader_pct_col and pd.notna(row.get(leader_pct_col)):
            leader_pct = round(float(row[leader_pct_col]), 2)
        items.append(
            SectorFlowItem(
                name=str(row[name_col]).strip(),
                net_inflow_yi=round(float(row["净额"]), 2),
                change_pct=round(float(row[pct_col]), 2)
                if pct_col and pd.notna(row.get(pct_col))
                else None,
                flow_type=flow_type,
                inflow_yi=round(float(inflow), 2)
                if inflow is not None and pd.notna(inflow)
                else None,
                outflow_yi=round(float(outflow), 2)
                if outflow is not None and pd.notna(outflow)
                else None,
                leader_stock=leader or None,
                leader_change_pct=leader_pct,
            )
        )

    inflows = sorted(items, key=lambda x: x.net_inflow_yi, reverse=True)[:top_n]
    outflows = sorted(items, key=lambda x: x.net_inflow_yi)[:top_n]
    return inflows, outflows


def _parse_net_yi(row: pd.Series) -> float | None:
    """优先成交净买额，其次资金净流入；无效时返回 None。"""
    for col in ("成交净买额", "资金净流入"):
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        try:
            return round(float(val), 2)
        except (TypeError, ValueError):
            continue
    return None


def _fetch_northbound_from_df(df: pd.DataFrame) -> NorthboundFlow | None:
    if df is None or df.empty:
        return None

    trade_date = str(df.iloc[0].get("交易日", date.today().isoformat()))
    sh_net: float | None = None
    sz_net: float | None = None
    sh_seen = sz_seen = False

    for _, row in df.iterrows():
        if str(row.get("资金方向", "")).strip() != "北向":
            continue
        board = str(row.get("板块", ""))
        net = _parse_net_yi(row)
        if "沪股通" in board and "港股通" not in board:
            sh_net = (sh_net or 0) + net if net is not None else sh_net
            sh_seen = True
        elif "深股通" in board and "港股通" not in board:
            sz_net = (sz_net or 0) + net if net is not None else sz_net
            sz_seen = True

    has_value = any(v is not None and v != 0 for v in (sh_net, sz_net))
    if not has_value and (sh_seen or sz_seen):
        return NorthboundFlow(
            trade_date=trade_date,
            sh_net_yi=None,
            sz_net_yi=None,
            total_net_yi=None,
            direction="unavailable",
            disclosed=False,
            note=NORTHBOUND_DISCLOSURE_NOTE,
        )

    total = round((sh_net or 0) + (sz_net or 0), 2) if has_value else None
    return NorthboundFlow(
        trade_date=trade_date,
        sh_net_yi=sh_net,
        sz_net_yi=sz_net,
        total_net_yi=total,
        direction=_direction_from_net(total or 0, threshold=10.0) if total is not None else "neutral",
        disclosed=True,
    )


def _fetch_southbound(df: pd.DataFrame, trade_date: str) -> SouthboundFlow | None:
    sh_net: float | None = None
    sz_net: float | None = None
    for _, row in df.iterrows():
        if str(row.get("资金方向", "")).strip() != "南向":
            continue
        board = str(row.get("板块", ""))
        net = _parse_net_yi(row)
        if net is None:
            continue
        if "港股通(沪)" in board or ("沪" in board and "港股通" in board):
            sh_net = (sh_net or 0) + net
        elif "港股通(深)" in board or ("深" in board and "港股通" in board):
            sz_net = (sz_net or 0) + net

    if sh_net is None and sz_net is None:
        return None
    total = round((sh_net or 0) + (sz_net or 0), 2)
    return SouthboundFlow(
        trade_date=trade_date,
        sh_net_yi=sh_net,
        sz_net_yi=sz_net,
        total_net_yi=total,
    )


def _match_theme_flows(
    all_items: list[SectorFlowItem],
    themes: set[str],
    theme_keywords: dict[str, list[str]],
) -> list[SectorFlowItem]:
    if not themes:
        return []

    keywords: set[str] = set()
    for theme in themes:
        keywords.add(theme)
        for kw in theme_keywords.get(theme, DEFAULT_THEME_KEYWORDS.get(theme, [])):
            keywords.add(kw)

    matched: list[SectorFlowItem] = []
    seen: set[str] = set()
    for item in all_items:
        if any(kw in item.name for kw in keywords):
            key = f"{item.flow_type}:{item.name}"
            if key not in seen:
                seen.add(key)
                matched.append(item)

    return sorted(matched, key=lambda x: x.net_inflow_yi, reverse=True)[:8]


def _infer_overall_direction(
    northbound: NorthboundFlow | None,
    top_inflows: list[SectorFlowItem],
    top_outflows: list[SectorFlowItem],
) -> tuple[str, str]:
    score = 0.0
    if northbound:
        score += (northbound.total_net_yi or 0) / 20.0

    if top_inflows:
        score += sum(x.net_inflow_yi for x in top_inflows[:3]) / 300.0
    if top_outflows:
        score -= sum(abs(x.net_inflow_yi) for x in top_outflows[:3]) / 300.0

    if score >= 0.35:
        return "inflow", "主力偏多（净流入）"
    if score <= -0.35:
        return "outflow", "主力偏空（净流出）"
    return "neutral", "主力方向中性"


def fetch_capital_flow_snapshot(
    strategy: dict,
    positions: list[dict[str, str]],
    universe: list[dict[str, str]],
) -> CapitalFlowSnapshot:
    cfg = strategy.get("market_flow") or {}
    if not cfg.get("enabled", True):
        return CapitalFlowSnapshot(error="market_flow 已禁用")

    top_n = int(cfg.get("top_sectors", 5))
    include_concepts = cfg.get("include_concepts", True)
    interval = float(cfg.get("request_interval_sec", 1.0))
    theme_keywords = {**DEFAULT_THEME_KEYWORDS, **(cfg.get("theme_keywords") or {})}

    themes: set[str] = set()
    for row in positions + universe:
        theme = (row.get("theme") or "").strip()
        if theme and theme not in ("推荐池", "未分类"):
            themes.add(theme)

    errors: list[str] = []
    sources: list[str] = []
    all_sectors: list[SectorFlowItem] = []
    top_inflows: list[SectorFlowItem] = []
    top_outflows: list[SectorFlowItem] = []
    trade_date = date.today().isoformat()

    try:
        ind_df = ak.stock_fund_flow_industry()
        sources.append("stock_fund_flow_industry")
        inflow, outflow = _parse_sector_df(ind_df, "industry", top_n)
        top_inflows.extend(inflow)
        top_outflows.extend(outflow)
        all_sectors.extend(inflow + outflow)
        if not ind_df.empty and "行业" in ind_df.columns:
            pass
    except Exception as e:
        errors.append(f"行业资金流: {e}")

    if include_concepts:
        time.sleep(interval)
        try:
            con_df = ak.stock_fund_flow_concept()
            sources.append("stock_fund_flow_concept")
            inflow, outflow = _parse_sector_df(con_df, "concept", top_n)
            top_inflows = sorted(
                top_inflows + inflow, key=lambda x: x.net_inflow_yi, reverse=True
            )[:top_n]
            top_outflows = sorted(top_outflows + outflow, key=lambda x: x.net_inflow_yi)[
                :top_n
            ]
            all_sectors.extend(inflow + outflow)
        except Exception as e:
            errors.append(f"概念资金流: {e}")

    northbound: NorthboundFlow | None = None
    southbound: SouthboundFlow | None = None
    time.sleep(interval)
    try:
        summary_df = ak.stock_hsgt_fund_flow_summary_em()
        northbound = _fetch_northbound_from_df(summary_df)
        southbound = _fetch_southbound(summary_df, str(summary_df.iloc[0].get("交易日", trade_date)))
        if northbound:
            sources.append("stock_hsgt_fund_flow_summary_em")
            trade_date = northbound.trade_date
    except Exception as e:
        errors.append(f"北向资金: {e}")

    theme_relevant = _match_theme_flows(all_sectors, themes, theme_keywords)
    overall_dir, overall_label = _infer_overall_direction(
        northbound, top_inflows, top_outflows
    )

    if not sources:
        return CapitalFlowSnapshot(
            error="; ".join(errors) or "未能拉取任何资金流数据"
        )

    return CapitalFlowSnapshot(
        trade_date=trade_date,
        overall_direction=overall_dir,
        overall_label=overall_label,
        northbound=northbound,
        southbound=southbound,
        top_inflows=top_inflows,
        top_outflows=top_outflows,
        theme_relevant=theme_relevant,
        data_source="+".join(sources),
        error="; ".join(errors) if errors else None,
    )
