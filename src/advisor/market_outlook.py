"""结合资金流、新闻与政策，生成 AI 短期方向研判。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.advisor.llm_client import chat_json, is_llm_configured
from src.analytics.portfolio import PortfolioSummary
from src.collectors.capital_flow import CapitalFlowSnapshot
from src.config_loader import ROOT

PROMPT_PATH = ROOT / "prompts" / "market_outlook_v1.txt"
VALID_BIAS = frozenset({"bullish", "neutral", "bearish"})


@dataclass
class MarketOutlook:
    horizon: str = "1-2周"
    overall_bias: str = "neutral"
    capital_flow_view: str = ""
    policy_event_view: str = ""
    theme_outlook: list[dict[str, Any]] = field(default_factory=list)
    key_risks: list[str] = field(default_factory=list)
    confidence: float = 0.5
    disclaimer: str = "以上仅为信息整理与方向研判，不构成投资建议。"
    skipped: bool = False
    skip_reason: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "overall_bias": self.overall_bias,
            "capital_flow_view": self.capital_flow_view,
            "policy_event_view": self.policy_event_view,
            "theme_outlook": self.theme_outlook,
            "key_risks": self.key_risks,
            "confidence": round(self.confidence, 2),
            "disclaimer": self.disclaimer,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "model": self.model,
        }


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _validate_outlook(raw: dict[str, Any]) -> dict[str, Any]:
    bias = str(raw.get("overall_bias") or "neutral").lower()
    if bias not in VALID_BIAS:
        bias = "neutral"

    themes_out: list[dict[str, Any]] = []
    for item in raw.get("theme_outlook") or []:
        tb = str(item.get("bias") or "neutral").lower()
        if tb not in VALID_BIAS:
            tb = "neutral"
        theme = str(item.get("theme") or "").strip()
        if not theme:
            continue
        themes_out.append(
            {
                "theme": theme,
                "bias": tb,
                "reason": str(item.get("reason") or "").strip() or "—",
            }
        )

    conf = float(raw.get("confidence") or 0.5)
    conf = max(0.0, min(1.0, conf))

    risks = [
        str(x).strip()
        for x in (raw.get("key_risks") or [])
        if str(x).strip()
    ][:5]

    return {
        "horizon": str(raw.get("horizon") or "1-2周").strip() or "1-2周",
        "overall_bias": bias,
        "capital_flow_view": str(raw.get("capital_flow_view") or "").strip(),
        "policy_event_view": str(raw.get("policy_event_view") or "").strip(),
        "theme_outlook": themes_out,
        "key_risks": risks,
        "confidence": conf,
        "disclaimer": str(raw.get("disclaimer") or "").strip()
        or "以上仅为信息整理与方向研判，不构成投资建议。",
    }


def _fallback_outlook(
    capital_flow: CapitalFlowSnapshot | None,
    news_digest: list[dict] | None,
) -> MarketOutlook:
    """无 LLM 时基于规则生成简要方向。"""
    cf = capital_flow
    parts: list[str] = []
    if cf and not cf.error:
        parts.append(
            f"程序判定主力方向：{cf.overall_label}。"
            f"净流入前列：{', '.join(x.name for x in cf.top_inflows[:3]) or '—'}。"
        )
        if cf.northbound:
            nb = cf.northbound
            if nb.disclosed and nb.total_net_yi is not None:
                parts.append(
                    f"北向合计 {nb.total_net_yi:+.2f} 亿元（沪 {nb.sh_net_yi:+.2f} / 深 {nb.sz_net_yi:+.2f}）。"
                )
            else:
                parts.append("北向日度净买额目前已暂停披露。")
    else:
        parts.append("今日未能获取完整资金流数据。")

    policy_parts: list[str] = []
    for item in (news_digest or [])[:3]:
        title = item.get("title") or item.get("summary") or ""
        if title:
            policy_parts.append(str(title)[:60])

    bias = "neutral"
    if cf and cf.overall_direction == "inflow":
        bias = "bullish"
    elif cf and cf.overall_direction == "outflow":
        bias = "bearish"

    return MarketOutlook(
        horizon="1-2周",
        overall_bias=bias,
        capital_flow_view="".join(parts),
        policy_event_view="；".join(policy_parts) or "暂无相关要闻摘要。",
        theme_outlook=[],
        key_risks=["数据不完整时方向判断可靠性下降"],
        confidence=0.35 if cf and cf.error else 0.45,
        skipped=True,
        skip_reason="未配置 LLM 或已禁用 AI 方向分析",
    )


def build_outlook_context(
    report_date: str,
    data_as_of: str,
    portfolio: PortfolioSummary,
    capital_flow: CapitalFlowSnapshot | None,
    news_digest: list[dict] | None,
    strategy: dict,
    positions_cfg: list[dict[str, str]],
    universe: list[dict[str, str]],
) -> dict[str, Any]:
    themes = sorted(
        {
            (row.get("theme") or "").strip()
            for row in positions_cfg + universe
            if (row.get("theme") or "").strip()
            and (row.get("theme") or "").strip() not in ("推荐池", "未分类")
        }
    )

    benchmark = None
    if portfolio.benchmark:
        b = portfolio.benchmark
        benchmark = {
            "name": b.name,
            "trade_date": str(b.trade_date),
            "daily_change_pct": b.daily_change_pct,
        }

    return {
        "date": report_date,
        "data_as_of": data_as_of,
        "portfolio_themes": themes,
        "benchmark": benchmark,
        "capital_flow": capital_flow.to_dict() if capital_flow else None,
        "news_digest": news_digest or [],
        "investor_notes": (strategy.get("investor") or {}).get("notes", ""),
    }


def generate_market_outlook(
    report_date: str,
    data_as_of: str,
    portfolio: PortfolioSummary,
    capital_flow: CapitalFlowSnapshot | None,
    news_digest: list[dict] | None,
    strategy: dict,
    positions_cfg: list[dict[str, str]],
    universe: list[dict[str, str]],
    *,
    use_llm: bool = True,
) -> MarketOutlook:
    cfg = strategy.get("market_outlook") or {}
    if not cfg.get("enabled", True):
        return MarketOutlook(
            skipped=True,
            skip_reason="market_outlook 已禁用",
        )

    if not use_llm or not is_llm_configured():
        return _fallback_outlook(capital_flow, news_digest)

    ctx = build_outlook_context(
        report_date,
        data_as_of,
        portfolio,
        capital_flow,
        news_digest,
        strategy,
        positions_cfg,
        universe,
    )
    system = _load_prompt()
    user = (
        "以下是今日资金流、持仓主题与要闻 JSON，请输出方向研判 JSON：\n\n"
        + json.dumps(ctx, ensure_ascii=False, indent=2)
    )

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    try:
        parsed, _ = chat_json(system, user)
        validated = _validate_outlook(parsed)
        return MarketOutlook(
            **validated,
            skipped=False,
            model=model,
        )
    except Exception as e:
        fb = _fallback_outlook(capital_flow, news_digest)
        fb.skip_reason = f"LLM 方向分析失败: {e}"
        return fb
