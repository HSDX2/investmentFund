"""从东方财富拉取开放式基金排行并缓存。"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd

from src.config_loader import ROOT

CACHE_DIR = ROOT / "data" / "fund_rank"
CACHE_HOURS = 6

COLUMNS = [
    "基金代码",
    "基金简称",
    "日期",
    "单位净值",
    "日增长率",
    "近1月",
    "近3月",
    "近6月",
    "近1年",
    "今年来",
    "成立来",
    "手续费",
]


def _cache_path(fund_type: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = fund_type.replace("/", "_")
    return CACHE_DIR / f"{safe}.csv"


def fetch_fund_rank_by_type(fund_type: str, use_cache: bool = True) -> pd.DataFrame:
    path = _cache_path(fund_type)
    if use_cache and path.exists():
        age = datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)
        if age < timedelta(hours=CACHE_HOURS):
            df = pd.read_csv(path, encoding="utf-8-sig")
            return df

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            raw = ak.fund_open_fund_rank_em(symbol=fund_type)
            break
        except Exception as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    else:
        if path.exists():
            return pd.read_csv(path, encoding="utf-8-sig")
        raise last_err or RuntimeError(f"拉取 {fund_type} 排行失败")

    raw = raw.copy()
    raw["fund_type"] = fund_type
    keep = [c for c in COLUMNS if c in raw.columns] + ["fund_type"]
    df = raw[keep]
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return df


def fetch_all_ranks(fund_types: list[str], use_cache: bool = True) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for ft in fund_types:
        frames.append(fetch_fund_rank_by_type(ft, use_cache=use_cache))
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["基金代码"], keep="first")
    return merged
