"""全市场筛选 + AI 基金推荐。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.advisor.llm_client import chat_json, is_llm_configured
from src.advisor.news_summarizer import build_news_digest
from src.advisor.recommend_rules import (
    build_batch_schedule,
    enrich_candidate_pool,
    enforce_allocation_plan,
)
from src.analytics.screener import ScreenedFund
from src.config_loader import ROOT, load_fund_universe, load_positions, load_strategy
from src.notify.batch_state import save_batch_state

PROMPT_PATH = ROOT / "prompts" / "fund_recommend_v1.txt"
OUT_DIR = ROOT / "data" / "recommendations"


@dataclass
class FundRecommendResult:
    summary: str = ""
    budget_cny: float = 0
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    notes: str = ""
    screened_count: int = 0
    rule_warnings: list[str] = field(default_factory=list)
    batch_schedule: list[dict[str, Any]] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "budget_cny": self.budget_cny,
            "recommendations": self.recommendations,
            "notes": self.notes,
            "screened_count": self.screened_count,
            "rule_warnings": self.rule_warnings,
            "batch_schedule": self.batch_schedule,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "model": self.model,
        }


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _validate_recommendations(
    raw: dict[str, Any],
    candidates: list[ScreenedFund],
    budget: float,
    max_n: int,
    held_codes: set[str] | None = None,
) -> dict[str, Any]:
    code_map = {c.fund_code: c for c in candidates}
    held_codes = held_codes or set()
    out: list[dict[str, Any]] = []
    total = 0.0

    for item in raw.get("recommendations") or []:
        code = str(item.get("fund_code", "")).zfill(6)
        if code not in code_map and code not in held_codes:
            continue
        c = code_map.get(code)
        if not c:
            # 持仓加仓：候选池无排行数据时用 AI 提供的名称
            c = ScreenedFund(
                fund_code=code,
                fund_name=str(item.get("fund_name") or code),
                fund_type="持仓",
                unit_nav=None,
                return_1m=None,
                return_3m=None,
                return_6m=None,
                return_1y=None,
                return_ytd=None,
                fee="",
                score=0.0,
            )
        amount = float(item.get("amount_cny") or 0)
        if amount <= 0:
            continue
        total += amount
        conf = max(0.0, min(1.0, float(item.get("confidence") or 0.5)))
        action = str(item.get("action") or "buy").lower()
        if action not in ("buy", "dca", "add"):
            action = "buy"
        out.append(
            {
                "fund_code": code,
                "fund_name": c.fund_name,
                "action": action,
                "amount_cny": round(amount, 2),
                "weight_pct": round(amount / budget, 4) if budget > 0 else 0,
                "reason": str(item.get("reason") or "").strip() or "—",
                "risk_tag": str(item.get("risk_tag") or "medium"),
                "confidence": round(conf, 2),
                "return_1y": c.return_1y,
                "fund_type": c.fund_type,
                "is_broad_index": bool(item.get("is_broad_index", False)),
            }
        )
        if len(out) >= max_n:
            break

    return {
        "summary": str(raw.get("summary") or "").strip(),
        "budget_cny": budget,
        "recommendations": out,
        "notes": str(raw.get("notes") or "").strip(),
        "allocated_total": round(total, 2),
    }


def build_recommend_context(
    screened: list[ScreenedFund],
    strategy: dict,
    positions: list[dict[str, str]],
    universe: list[dict[str, str]],
    news_digest: list[dict] | None = None,
) -> dict[str, Any]:
    rec = strategy.get("recommendation", {})
    trading = strategy.get("trading", {})
    return {
        "date": date.today().isoformat(),
        "budget_cny": rec.get("budget_cny", 5000),
        "investor": strategy.get("investor", {}),
        "allocation": strategy.get("allocation", {}),
        "allocation_plan": rec.get("allocation_plan", {}),
        "batch_plan": rec.get("batch_plan", {}),
        "portfolio_plan": strategy.get("portfolio_plan", {}),
        "current_positions": positions,
        "watchlist": universe,
        "dca_only_funds": trading.get("dca_only_funds", []),
        "candidates": [c.to_dict() for c in screened],
        "news_digest": news_digest or [],
    }


def generate_fund_recommendations(
    screened: list[ScreenedFund],
    *,
    use_llm: bool = True,
    strategy_override: dict | None = None,
) -> FundRecommendResult:
    strategy = strategy_override or load_strategy()
    rec_cfg = strategy.get("recommendation", {})
    budget = float(rec_cfg.get("budget_cny", 5000))
    max_n = int(rec_cfg.get("max_recommendations", 5))
    positions = load_positions()
    universe = load_fund_universe()

    if not screened:
        return FundRecommendResult(
            skipped=True,
            skip_reason="筛选结果为空，请检查网络或 recommendation 配置",
        )

    if not use_llm or not is_llm_configured():
        return FundRecommendResult(
            screened_count=len(screened),
            budget_cny=budget,
            skipped=True,
            skip_reason="未配置 LLM_API_KEY",
        )

    news_digest, _ = build_news_digest(
        strategy, positions, universe, use_llm=use_llm
    )
    ctx = build_recommend_context(
        screened, strategy, positions, universe, news_digest=news_digest
    )
    system = _load_prompt()
    user = (
        "以下是用户策略、持仓与候选基金 JSON，请输出推荐配置 JSON：\n\n"
        + json.dumps(ctx, ensure_ascii=False, indent=2)
    )

    import os
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    model = os.getenv("LLM_MODEL", "deepseek-chat")

    parsed, _ = chat_json(system, user)
    held = {p["fund_code"] for p in positions}
    validated = _validate_recommendations(
        parsed, screened, budget, max_n, held_codes=held
    )
    recs, rule_warnings = enforce_allocation_plan(
        validated["recommendations"], screened, rec_cfg, budget
    )
    batch_schedule = build_batch_schedule(
        recs, rec_cfg.get("batch_plan") or {}, budget
    )

    return FundRecommendResult(
        summary=validated["summary"],
        budget_cny=validated["budget_cny"],
        recommendations=recs,
        notes=validated.get("notes", ""),
        screened_count=len(screened),
        rule_warnings=rule_warnings,
        batch_schedule=batch_schedule,
        skipped=False,
        model=model,
    )


def render_recommend_markdown(
    result: FundRecommendResult,
    top_screened: list[ScreenedFund],
) -> str:
    lines = [
        f"# 基金推荐报告 {date.today().isoformat()}",
        "",
        "> 基于东方财富开放式基金排行筛选 + AI 分析。**不构成投资建议。**",
        "",
    ]
    if result.skipped:
        lines.extend([f"> {result.skip_reason}", ""])
        return "\n".join(lines)

    lines.extend(
        [
            f"**计划投入**：{result.budget_cny:,.0f} 元",
            f"**候选池**：从全市场排行筛选 {result.screened_count} 只",
            "",
            "## AI 配置思路",
            "",
            result.summary or "—",
            "",
            "## 推荐清单",
            "",
            "| 代码 | 名称 | 操作 | 金额(元) | 占比 | 近1年% | 类型 | 宽基 | 理由 |",
            "|------|------|------|----------|------|--------|------|------|------|",
        ]
    )
    for r in result.recommendations:
        broad = "宽基" if r.get("is_broad_index") else "—"
        lines.append(
            f"| {r['fund_code']} | {r['fund_name']} | {r['action']} | "
            f"{r['amount_cny']:,.0f} | {r['weight_pct']*100:.1f}% | "
            f"{r.get('return_1y') or '—'} | {r.get('fund_type','')} | {broad} | {r['reason']} |"
        )

    if result.rule_warnings:
        lines.extend(["", "## 规则校验", ""])
        for w in result.rule_warnings:
            lines.append(f"- {w}")

    if result.batch_schedule:
        lines.extend(["", "## 分批买入计划（建议不要一天打满）", ""])
        for batch in result.batch_schedule:
            if batch.get("batch") == "daily":
                item = batch["items"][0]
                lines.append(
                    f"- **{batch['label']}**：{item.get('fund_code')} "
                    f"每天 **{item['amount_cny']}** 元 — {item.get('note', '')}"
                )
                continue
            lines.append(f"### {batch['label']}，合计 **{batch['batch_total_cny']:,.0f}** 元")
            lines.append("")
            lines.append("| 代码 | 名称 | 操作 | 本批金额(元) |")
            lines.append("|------|------|------|--------------|")
            for item in batch.get("items", []):
                lines.append(
                    f"| {item['fund_code']} | {item['fund_name']} | {item['action']} | "
                    f"{item['amount_cny']:,.0f} |"
                )
            lines.append("")

    if result.notes:
        lines.extend(["", "## 备注", "", result.notes, ""])

    lines.extend(
        [
            "",
            "## 候选池 Top 10（程序评分）",
            "",
            "| 代码 | 名称 | 类型 | 近1年% | 评分 |",
            "|------|------|------|--------|------|",
        ]
    )
    for c in top_screened[:10]:
        lines.append(
            f"| {c.fund_code} | {c.fund_name} | {c.fund_type} | "
            f"{c.return_1y or '—'} | {c.score} |"
        )
    lines.append("")
    return "\n".join(lines)


def save_recommendation(
    result: FundRecommendResult, markdown: str, report_date: date | None = None
) -> tuple[Path, Path]:
    d = report_date or date.today()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / f"{d.isoformat()}.json"
    md_path = reports_dir / f"fund-recommend-{d.isoformat()}.md"
    json_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(markdown, encoding="utf-8")
    if result.batch_schedule:
        save_batch_state(d, result.budget_cny, result.batch_schedule)
    return json_path, md_path
