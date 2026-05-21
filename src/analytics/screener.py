"""从全市场排行中按策略规则筛选候选基金。"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass
class ScreenedFund:
    fund_code: str
    fund_name: str
    fund_type: str
    unit_nav: float | None
    return_1m: float | None
    return_3m: float | None
    return_6m: float | None
    return_1y: float | None
    return_ytd: float | None
    fee: str
    score: float

    def to_dict(self) -> dict:
        return asdict(self)


def _num(val) -> float | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _theme_bonus(name: str, themes: list[str]) -> float:
    bonus = 0.0
    for i, t in enumerate(themes):
        if t and t in name:
            bonus += max(0, (len(themes) - i) * 2)
    return bonus


def screen_funds(df: pd.DataFrame, rec_cfg: dict) -> list[ScreenedFund]:
    if df.empty:
        return []

    exclude_kw = rec_cfg.get("exclude_name_keywords") or []
    min_1y = rec_cfg.get("min_return_1y")
    prefer_themes = rec_cfg.get("prefer_themes") or []
    max_n = int(rec_cfg.get("max_candidates", 60))

    rows: list[ScreenedFund] = []
    for _, r in df.iterrows():
        code = str(r["基金代码"]).zfill(6)
        name = str(r.get("基金简称", ""))
        if any(kw in name for kw in exclude_kw):
            continue

        ret_1y = _num(r.get("近1年"))
        if min_1y is not None and ret_1y is not None and ret_1y < float(min_1y):
            continue

        ret_3m = _num(r.get("近3月"))
        ret_6m = _num(r.get("近6月"))
        ret_1m = _num(r.get("近1月"))
        ret_ytd = _num(r.get("今年来"))

        # 综合分：偏中长期，避免只看近1周暴涨
        score = 0.0
        if ret_1y is not None:
            score += ret_1y * 0.4
        if ret_6m is not None:
            score += ret_6m * 0.25
        if ret_3m is not None:
            score += ret_3m * 0.2
        if ret_ytd is not None:
            score += ret_ytd * 0.15
        score += _theme_bonus(name, prefer_themes)

        rows.append(
            ScreenedFund(
                fund_code=code,
                fund_name=name,
                fund_type=str(r.get("fund_type", "")),
                unit_nav=_num(r.get("单位净值")),
                return_1m=ret_1m,
                return_3m=ret_3m,
                return_6m=ret_6m,
                return_1y=ret_1y,
                return_ytd=ret_ytd,
                fee=str(r.get("手续费", "")),
                score=round(score, 2),
            )
        )

    rows.sort(key=lambda x: x.score, reverse=True)
    return rows[:max_n]
