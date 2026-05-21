"""推荐候选池补全与分配规则强制执行。"""

from __future__ import annotations

from src.analytics.screener import ScreenedFund, screen_funds


def _code(row) -> str:
    return str(row["基金代码"]).zfill(6)


def is_broad_index(name: str, keywords: list[str]) -> bool:
    return any(kw in name for kw in keywords)


def enrich_candidate_pool(
    df,
    screened: list[ScreenedFund],
    rec_cfg: dict,
    strategy: dict,
) -> list[ScreenedFund]:
    """确保主仓、宽基指数类基金进入 AI 候选池。"""
    plan = rec_cfg.get("allocation_plan") or {}
    portfolio = strategy.get("portfolio_plan") or {}
    core = str(plan.get("core_fund") or portfolio.get("core_fund") or "").zfill(6)
    broad_kw = plan.get("broad_index_keywords") or ["沪深300", "中证500"]
    max_n = int(rec_cfg.get("max_candidates", 60))

    by_code = {c.fund_code: c for c in screened}

    if core and core not in by_code and not df.empty:
        hit = df[df["基金代码"].astype(str).str.zfill(6) == core]
        if not hit.empty:
            extra = screen_funds(hit, rec_cfg)
            if extra:
                by_code[core] = extra[0]

    if not df.empty:
        broad_rows = df[
            df["基金简称"].astype(str).apply(lambda n: is_broad_index(n, broad_kw))
        ]
        broad_screened = screen_funds(broad_rows, {**rec_cfg, "max_candidates": 20})
        for c in broad_screened[:10]:
            by_code[c.fund_code] = c

    merged = sorted(by_code.values(), key=lambda x: x.score, reverse=True)
    # 保留得分 Top，但强制留出宽基名额
    broad_codes = [c.fund_code for c in merged if is_broad_index(c.fund_name, broad_kw)]
    top = [c for c in merged if c.fund_code not in broad_codes][: max(0, max_n - min(3, len(broad_codes)))]
    broad_keep = [c for c in merged if c.fund_code in broad_codes][:3]
    final = sorted(top + broad_keep, key=lambda x: x.score, reverse=True)
    return final[:max_n]


def enforce_allocation_plan(
    recommendations: list[dict],
    screened: list[ScreenedFund],
    rec_cfg: dict,
    budget: float,
) -> tuple[list[dict], list[str]]:
    """校验并补全：主仓加仓 + 宽基占比。"""
    plan = rec_cfg.get("allocation_plan") or {}
    warnings: list[str] = []
    code_map = {c.fund_code: c for c in screened}
    reserve = float(plan.get("reserve_cash_ratio", 0.05))
    deployable = budget * (1 - reserve)

    core = str(plan.get("core_fund", "")).zfill(6)
    min_core = float(plan.get("min_core_add_cny", 1000))
    broad_ratio = float(plan.get("broad_index_min_ratio", 0.5))
    broad_kw = plan.get("broad_index_keywords") or ["沪深300", "中证500"]

    recs = list(recommendations)

    if plan.get("require_core_add") and core:
        core_recs = [r for r in recs if r["fund_code"] == core]
        core_amount = sum(r["amount_cny"] for r in core_recs)
        if core_amount < min_core:
            if core in code_map:
                c = code_map[core]
                if core_recs:
                    for r in recs:
                        if r["fund_code"] == core:
                            r["amount_cny"] = round(min_core, 2)
                            r["action"] = "add"
                            r["reason"] = f"[规则补全] 主仓 {c.fund_name} 至少加仓 {min_core:.0f} 元"
                else:
                    recs.append(
                        {
                            "fund_code": core,
                            "fund_name": c.fund_name,
                            "action": "add",
                            "amount_cny": round(min_core, 2),
                            "weight_pct": round(min_core / budget, 4),
                            "reason": f"[规则补全] 已有主仓，建议加仓 {min_core:.0f} 元",
                            "risk_tag": "high",
                            "confidence": 0.85,
                            "return_1y": c.return_1y,
                            "fund_type": c.fund_type,
                            "is_broad_index": False,
                        }
                    )
                warnings.append(f"已补全主仓 {core} 加仓 ≥{min_core:.0f} 元")
            else:
                warnings.append(f"主仓 {core} 不在候选池，无法自动补全加仓")

    broad_total = sum(
        r["amount_cny"]
        for r in recs
        if is_broad_index(r.get("fund_name", ""), broad_kw)
    )
    need_broad = deployable * broad_ratio
    if broad_total < need_broad:
        best_broad = next(
            (
                c
                for c in sorted(screened, key=lambda x: x.score, reverse=True)
                if is_broad_index(c.fund_name, broad_kw) and c.fund_code != core
            ),
            None,
        )
        if best_broad:
            gap = round(need_broad - broad_total, 2)
            existing = next((r for r in recs if r["fund_code"] == best_broad.fund_code), None)
            if existing:
                existing["amount_cny"] = round(existing["amount_cny"] + gap, 2)
                existing["reason"] += f"；[规则补全] 宽基合计需达 {broad_ratio*100:.0f}%"
            else:
                recs.append(
                    {
                        "fund_code": best_broad.fund_code,
                        "fund_name": best_broad.fund_name,
                        "action": "buy",
                        "amount_cny": gap,
                        "weight_pct": round(gap / budget, 4),
                        "reason": f"[规则补全] 宽基指数合计需 ≥{broad_ratio*100:.0f}%，补充 {best_broad.fund_name}",
                        "risk_tag": "medium",
                        "confidence": 0.8,
                        "return_1y": best_broad.return_1y,
                        "fund_type": best_broad.fund_type,
                        "is_broad_index": True,
                    }
                )
            warnings.append(f"已补全宽基至合计 ≥{broad_ratio*100:.0f}%")

    total = sum(r["amount_cny"] for r in recs)
    if total > deployable:
        scale = deployable / total
        for r in recs:
            r["amount_cny"] = round(r["amount_cny"] * scale, 2)
            r["weight_pct"] = round(r["amount_cny"] / budget, 4)
        warnings.append(f"总额超限，已按比例缩至 {deployable:.0f} 元内")

    for r in recs:
        r["is_broad_index"] = is_broad_index(r.get("fund_name", ""), broad_kw)

    return recs, warnings


def build_batch_schedule(
    recommendations: list[dict],
    batch_cfg: dict,
    budget: float,
) -> list[dict]:
    """生成分批买入计划。"""
    if not batch_cfg.get("enabled", True):
        return []

    tranches = int(batch_cfg.get("tranches", 3))
    days_between = int(batch_cfg.get("days_between", 7))
    dca_fund = str(batch_cfg.get("dca_fund", "")).zfill(6)
    dca_daily = float(batch_cfg.get("dca_daily_cny", 10))

    schedule: list[dict] = []
    for t in range(tranches):
        day_offset = t * days_between
        items = []
        for r in recommendations:
            if r.get("action") == "dca":
                continue
            part = round(r["amount_cny"] / tranches, 2)
            if t == tranches - 1:
                part = round(
                    r["amount_cny"] - round(r["amount_cny"] / tranches, 2) * (tranches - 1),
                    2,
                )
            items.append(
                {
                    "fund_code": r["fund_code"],
                    "fund_name": r["fund_name"],
                    "action": r["action"],
                    "amount_cny": part,
                }
            )
        batch_total = sum(i["amount_cny"] for i in items)
        schedule.append(
            {
                "batch": t + 1,
                "day_offset": day_offset,
                "label": f"第{t + 1}批（建议 T+{day_offset} 日起）",
                "items": items,
                "batch_total_cny": round(batch_total, 2),
            }
        )

    if dca_fund:
        schedule.append(
            {
                "batch": "daily",
                "label": f"每日定投（与 5000 分批并行）",
                "items": [
                    {
                        "fund_code": dca_fund,
                        "action": "dca",
                        "amount_cny": dca_daily,
                        "note": batch_cfg.get("note", ""),
                    }
                ],
            }
        )
    return schedule
