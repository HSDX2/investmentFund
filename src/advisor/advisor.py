"""Phase 2：规则 + LLM 投资建议。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.advisor.context import build_advisor_context, theme_map
from src.advisor.llm_client import chat_json, is_llm_configured
from src.advisor.news_summarizer import build_news_digest
from src.advisor.validator import validate_advice
from src.analytics.portfolio import PortfolioSummary, WatchlistItem
from src.analytics.trend_observation import build_trend_observation
from src.config_loader import ROOT
from src.risk.rules import RuleSignal, enforce_critical_rules, evaluate_rules

PROMPT_PATH = ROOT / "prompts" / "daily_advice_v1.txt"
ADVICE_DIR = ROOT / "data" / "advice"


@dataclass
class AdviceResult:
    market_summary: str = ""
    overall_risk_level: str = "medium"
    actions: list[dict[str, Any]] = field(default_factory=list)
    switch_candidates: list[dict[str, Any]] = field(default_factory=list)
    rule_signals: list[RuleSignal] = field(default_factory=list)
    news_digest: list[dict[str, Any]] = field(default_factory=list)
    news_error: str | None = None
    trend_observation: dict[str, Any] | None = None
    skipped: bool = False
    skip_reason: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_summary": self.market_summary,
            "overall_risk_level": self.overall_risk_level,
            "actions": self.actions,
            "switch_candidates": self.switch_candidates,
            "rule_signals": [s.to_dict() for s in self.rule_signals],
            "news_digest": self.news_digest,
            "news_error": self.news_error,
            "trend_observation": self.trend_observation,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "model": self.model,
        }


def _whitelist(
    universe: list[dict[str, str]], positions_cfg: list[dict[str, str]]
) -> set[str]:
    codes: set[str] = set()
    for row in universe + positions_cfg:
        c = row.get("fund_code", "").strip()
        if c:
            codes.add(c)
    return codes


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def generate_advice(
    report_date: date,
    data_as_of: str,
    portfolio: PortfolioSummary,
    watchlist: list[WatchlistItem],
    strategy: dict,
    fund_universe: list[dict[str, str]],
    positions_cfg: list[dict[str, str]],
    *,
    use_llm: bool = True,
) -> AdviceResult:
    themes = theme_map(fund_universe)
    for pos in positions_cfg:
        if pos["fund_code"] not in themes:
            themes[pos["fund_code"]] = "未分类"

    rule_signals = evaluate_rules(
        portfolio, strategy, positions_cfg, themes
    )
    whitelist = _whitelist(fund_universe, positions_cfg)

    news_digest, news_error = build_news_digest(
        strategy,
        positions_cfg,
        fund_universe,
        use_llm=use_llm,
    )
    trend_observation = build_trend_observation(strategy, portfolio, positions_cfg)

    if not use_llm or not is_llm_configured():
        reason = (
            "未启用 AI（--no-ai）"
            if not use_llm
            else "未配置 LLM_API_KEY，请复制 .env.example 为 .env"
        )
        return AdviceResult(
            market_summary="",
            rule_signals=rule_signals,
            news_digest=news_digest,
            news_error=news_error,
            trend_observation=trend_observation,
            skipped=True,
            skip_reason=reason,
        )

    ctx = build_advisor_context(
        report_date.isoformat(),
        data_as_of,
        portfolio,
        watchlist,
        strategy,
        rule_signals,
        fund_universe,
        positions_cfg,
        news_digest=news_digest,
        trend_observation=trend_observation,
    )
    system = _load_system_prompt()
    user = (
        "以下是今日账户与规则扫描的 JSON 数据，请按系统提示输出投资建议 JSON：\n\n"
        + json.dumps(ctx, ensure_ascii=False, indent=2)
    )

    import os

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    parsed, _raw = chat_json(system, user)
    validated = validate_advice(parsed, whitelist)
    validated = enforce_critical_rules(validated, rule_signals, whitelist)

    return AdviceResult(
        market_summary=validated["market_summary"],
        overall_risk_level=validated["overall_risk_level"],
        actions=validated["actions"],
        switch_candidates=validated["switch_candidates"],
        rule_signals=rule_signals,
        news_digest=news_digest,
        news_error=news_error,
        trend_observation=trend_observation,
        skipped=False,
        model=model,
    )


def save_advice_audit(advice: AdviceResult, report_date: date | None = None) -> Path:
    d = report_date or date.today()
    ADVICE_DIR.mkdir(parents=True, exist_ok=True)
    path = ADVICE_DIR / f"{d.isoformat()}.json"
    path.write_text(
        json.dumps(advice.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
