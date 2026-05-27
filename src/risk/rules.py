"""硬规则扫描：优先于 AI，触发结果写入建议上下文。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime

from src.analytics.portfolio import PortfolioSummary, PositionMetrics


@dataclass
class RuleSignal:
    rule_id: str
    severity: str  # info | warning | critical
    fund_code: str | None
    message: str
    suggested_action: str  # hold | add | reduce | switch

    def to_dict(self) -> dict:
        return asdict(self)


def _days_since(date_str: str) -> int | None:
    try:
        d = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
        return (date.today() - d).days
    except ValueError:
        return None


def evaluate_rules(
    portfolio: PortfolioSummary,
    strategy: dict,
    positions_cfg: list[dict[str, str]],
    theme_by_code: dict[str, str],
) -> list[RuleSignal]:
    signals: list[RuleSignal] = []
    alloc = strategy.get("allocation", {})
    sig = strategy.get("signals", {})
    trading = strategy.get("trading", {})

    max_single = float(alloc.get("max_single_fund_ratio", 0.2)) * 100
    max_theme = float(alloc.get("max_theme_ratio", 0.4)) * 100
    relax_below = float(alloc.get("relax_caps_when_value_below", 0))
    stop_loss = float(sig.get("stop_loss_ratio", -0.15)) * 100
    take_profit = float(sig.get("take_profit_ratio", 0.30)) * 100
    min_switch_days = int(trading.get("min_days_between_switch", 30))

    caps_relaxed = relax_below > 0 and portfolio.total_market_value < relax_below
    if caps_relaxed:
        signals.append(
            RuleSignal(
                rule_id="SMALL_ACCOUNT_MODE",
                severity="info",
                fund_code=None,
                message=(
                    f"账户市值 {portfolio.total_market_value:.2f} 元 "
                    f"低于 {relax_below:.0f} 元，暂不检查单基/主题仓位上限"
                ),
                suggested_action="hold",
            )
        )

    # 单基仓位上限（小资金阶段可放宽）
    if not caps_relaxed:
        for p in portfolio.positions:
            if p.weight_pct > max_single:
                signals.append(
                    RuleSignal(
                        rule_id="POSITION_CAP",
                        severity="warning",
                        fund_code=p.fund_code,
                        message=f"{p.fund_name} 仓位 {p.weight_pct:.1f}% 超过上限 {max_single:.0f}%",
                        suggested_action="reduce",
                    )
                )

        # 主题集中度
        theme_weight: dict[str, float] = {}
        for p in portfolio.positions:
            theme = theme_by_code.get(p.fund_code, "未分类")
            theme_weight[theme] = theme_weight.get(theme, 0) + p.weight_pct
        for theme, w in theme_weight.items():
            if w > max_theme:
                signals.append(
                    RuleSignal(
                        rule_id="THEME_CAP",
                        severity="warning",
                        fund_code=None,
                        message=f"主题「{theme}」合计仓位 {w:.1f}% 超过上限 {max_theme:.0f}%",
                        suggested_action="reduce",
                    )
                )

    # 止损 / 止盈
    for p in portfolio.positions:
        if p.unrealized_pnl_pct <= stop_loss:
            signals.append(
                RuleSignal(
                    rule_id="STOP_LOSS",
                    severity="critical",
                    fund_code=p.fund_code,
                    message=f"{p.fund_name} 浮亏 {p.unrealized_pnl_pct:.2f}% 触及止损线 {stop_loss:.0f}%",
                    suggested_action="reduce",
                )
            )
        elif p.unrealized_pnl_pct >= take_profit:
            signals.append(
                RuleSignal(
                    rule_id="TAKE_PROFIT",
                    severity="info",
                    fund_code=p.fund_code,
                    message=f"{p.fund_name} 浮盈 {p.unrealized_pnl_pct:.2f}% 达到止盈观察线 {take_profit:.0f}%",
                    suggested_action="reduce",
                )
            )

    # 短期赎回预警（持有不足 7 天）— 按首次建仓日，加仓不重置
    for pos in positions_cfg:
        buy_date = pos.get("first_buy_date") or pos.get("last_buy_date", "")
        days = _days_since(buy_date)
        if days is not None and days < 7:
            signals.append(
                RuleSignal(
                    rule_id="REDEMPTION_FEE_7D",
                    severity="warning",
                    fund_code=pos["fund_code"],
                    message=f"{pos.get('fund_name', pos['fund_code'])} 距首次买入仅 {days} 天，赎回可能收取惩罚性费用",
                    suggested_action="hold",
                )
            )

    # 换基冷却 — 按最近一次买入日
    for pos in positions_cfg:
        days = _days_since(pos.get("last_buy_date", ""))
        if days is not None and days < min_switch_days:
            signals.append(
                RuleSignal(
                    rule_id="SWITCH_COOLDOWN",
                    severity="info",
                    fund_code=pos["fund_code"],
                    message=f"距上次买入 {days} 天，策略建议换基间隔不少于 {min_switch_days} 天",
                    suggested_action="hold",
                )
            )

    return signals


def enforce_critical_rules(
    advice: dict,
    rule_signals: list[RuleSignal],
    whitelist: set[str],
) -> dict:
    """止损等 critical 规则若 AI 未给出减仓，注入保底建议。"""
    actions = list(advice.get("actions") or [])
    existing = {(a.get("fund_code"), a.get("action")) for a in actions}

    for sig in rule_signals:
        if sig.severity != "critical" or not sig.fund_code:
            continue
        key = (sig.fund_code, "reduce")
        if key in existing:
            continue
        if sig.fund_code not in whitelist:
            continue
        actions.append(
            {
                "fund_code": sig.fund_code,
                "action": "reduce",
                "ratio": 0.1,
                "reason": f"[规则保底] {sig.message}",
                "confidence": 1.0,
                "rule_hits": [sig.rule_id],
                "requires_human_confirm": True,
            }
        )
        existing.add(key)

    advice["actions"] = actions
    return advice
