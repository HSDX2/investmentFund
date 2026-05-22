"""通过 AkShare 拉取开放式基金单位净值。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "data" / "nav"

CACHE_MAX_AGE_HOURS = 12
STALE_CACHE_MAX_DAYS = 7
MAX_RETRIES = 4


@dataclass
class FundNavSnapshot:
    fund_code: str
    nav_date: date
    unit_nav: float
    daily_growth_pct: float | None  # 日增长率，单位 %
    prev_nav_date: date | None
    prev_unit_nav: float | None
    data_source: str = ""

    @property
    def is_stale_cache(self) -> bool:
        return "缓存" in self.data_source


def _parse_nav_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["净值日期"] = pd.to_datetime(df["净值日期"])
    df = df.sort_values("净值日期").reset_index(drop=True)
    df["单位净值"] = pd.to_numeric(df["单位净值"], errors="coerce")
    if "日增长率" in df.columns:
        df["日增长率"] = pd.to_numeric(df["日增长率"], errors="coerce")
    return df.dropna(subset=["单位净值"])


def fetch_fund_nav_history(fund_code: str) -> pd.DataFrame:
    """拉取基金全部历史单位净值（东方财富），带重试。"""
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            raw = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
            return _parse_nav_df(raw)
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last_err or RuntimeError(f"拉取 {fund_code} 净值失败")


def _cache_path(fund_code: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{fund_code}.csv"


def _load_cache(cache_file: Path, max_age_days: int | None = None) -> pd.DataFrame | None:
    if not cache_file.exists():
        return None
    if max_age_days is not None:
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mtime > timedelta(days=max_age_days):
            return None
    return _parse_nav_df(pd.read_csv(cache_file, encoding="utf-8-sig"))


def _snapshot_from_df(
    df: pd.DataFrame, fund_code: str, *, data_source: str
) -> FundNavSnapshot:
    latest = df.iloc[-1]
    nav_date = latest["净值日期"].date()
    unit_nav = float(latest["单位净值"])
    growth = float(latest["日增长率"]) if pd.notna(latest.get("日增长率")) else None

    prev_date = None
    prev_nav = None
    if len(df) >= 2:
        prev = df.iloc[-2]
        prev_date = prev["净值日期"].date()
        prev_nav = float(prev["单位净值"])

    if growth is None and prev_nav and prev_nav > 0:
        growth = (unit_nav - prev_nav) / prev_nav * 100

    return FundNavSnapshot(
        fund_code=fund_code,
        nav_date=nav_date,
        unit_nav=unit_nav,
        daily_growth_pct=growth,
        prev_nav_date=prev_date,
        prev_unit_nav=prev_nav,
        data_source=data_source,
    )


def get_fund_nav_snapshot(fund_code: str, use_cache: bool = True) -> FundNavSnapshot:
    cache_file = _cache_path(fund_code)

    if use_cache and cache_file.exists():
        age_h = (datetime.now().timestamp() - cache_file.stat().st_mtime) / 3600
        if age_h < CACHE_MAX_AGE_HOURS:
            df = _load_cache(cache_file)
            if df is not None and len(df) > 0:
                return _snapshot_from_df(df, fund_code, data_source="本地缓存")

    try:
        df = fetch_fund_nav_history(fund_code)
        df.to_csv(cache_file, index=False, encoding="utf-8-sig")
        return _snapshot_from_df(df, fund_code, data_source="东方财富")
    except Exception as e:
        if use_cache:
            df = _load_cache(cache_file, max_age_days=STALE_CACHE_MAX_DAYS)
            if df is not None and len(df) > 0:
                print(
                    f"  [警告] {fund_code} 网络拉取失败，使用过期缓存（≤{STALE_CACHE_MAX_DAYS}天）: {e}"
                )
                return _snapshot_from_df(
                    df,
                    fund_code,
                    data_source=f"过期缓存（≤{STALE_CACHE_MAX_DAYS}天）",
                )
        raise


def fetch_all_snapshots(fund_codes: list[str]) -> dict[str, FundNavSnapshot]:
    result: dict[str, FundNavSnapshot] = {}
    for i, code in enumerate(fund_codes):
        if i > 0:
            time.sleep(1.0)
        result[code] = get_fund_nav_snapshot(code)
    return result
