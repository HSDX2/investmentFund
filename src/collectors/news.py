"""财经新闻采集（东方财富关键词搜索）。"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import akshare as ak

# 从基金名称/主题中提取搜索词
NAME_KEYWORD_HINTS = (
    "人工智能",
    "创新药",
    "纳斯达克",
    "通信",
    "科技",
    "红利",
    "沪深300",
    "中证500",
    "QDII",
    "美联储",
    "医药",
)
GENERIC_THEMES = {
    "指数型-股票",
    "指数型-海外股票",
    "宽基",
    "推荐池",
    "未分类",
    "high",
    "medium",
    "low",
}


@dataclass
class NewsItem:
    keyword: str
    title: str
    published_at: str
    source: str
    url: str
    content_preview: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_published_at(raw: str) -> datetime | None:
    raw = (raw or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", "", (title or "").strip())


def _content_preview(content: str, max_len: int = 120) -> str:
    text = re.sub(r"\s+", " ", (content or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def resolve_news_keywords(
    strategy: dict,
    positions: list[dict[str, str]],
    universe: list[dict[str, str]],
) -> list[str]:
    """合并配置关键词与持仓相关主题词。"""
    cfg = strategy.get("news") or {}
    keywords: list[str] = [str(k).strip() for k in cfg.get("keywords") or [] if str(k).strip()]

    if cfg.get("auto_keywords_from_holdings", True):
        theme_map = {row["fund_code"]: row.get("theme", "") for row in universe}
        name_map = {row["fund_code"]: row.get("fund_name", "") for row in universe}
        for pos in positions:
            code = pos["fund_code"]
            name = pos.get("fund_name") or name_map.get(code, "")
            theme = theme_map.get(code, "")
            if theme and theme not in GENERIC_THEMES and theme not in keywords:
                keywords.append(theme)
            for hint in NAME_KEYWORD_HINTS:
                if hint in name and hint not in keywords:
                    keywords.append(hint)

    # 去重保序
    seen: set[str] = set()
    out: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            out.append(kw)
    return out


def fetch_keyword_news(
    keyword: str,
    *,
    max_items: int = 5,
    max_age_hours: int = 72,
) -> list[NewsItem]:
    """按关键词拉取新闻，过滤过旧条目。"""
    try:
        df = ak.stock_news_em(symbol=keyword)
    except Exception:
        return []

    if df is None or df.empty:
        return []

    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    items: list[NewsItem] = []
    for _, row in df.iterrows():
        title = str(row.get("新闻标题") or "").strip()
        if not title:
            continue
        published = str(row.get("发布时间") or "").strip()
        dt = _parse_published_at(published)
        if dt and dt < cutoff:
            continue
        items.append(
            NewsItem(
                keyword=keyword,
                title=title,
                published_at=published,
                source=str(row.get("文章来源") or "").strip(),
                url=str(row.get("新闻链接") or "").strip(),
                content_preview=_content_preview(str(row.get("新闻内容") or "")),
            )
        )
        if len(items) >= max_items:
            break
    return items


def collect_news_items(
    strategy: dict,
    positions: list[dict[str, str]],
    universe: list[dict[str, str]],
) -> tuple[list[NewsItem], str | None]:
    """拉取去重后的新闻列表。返回 (items, error)。"""
    cfg = strategy.get("news") or {}
    if not cfg.get("enabled", False):
        return [], None

    keywords = resolve_news_keywords(strategy, positions, universe)
    if not keywords:
        return [], None

    max_per_keyword = int(cfg.get("max_per_keyword", 3))
    max_total = int(cfg.get("max_total", 12))
    max_age_hours = int(cfg.get("max_age_hours", 72))
    sleep_sec = float(cfg.get("request_interval_sec", 1.0))

    merged: list[NewsItem] = []
    seen_titles: set[str] = set()
    last_err: str | None = None

    for i, keyword in enumerate(keywords):
        if i > 0 and sleep_sec > 0:
            time.sleep(sleep_sec)
        try:
            batch = fetch_keyword_news(
                keyword,
                max_items=max_per_keyword,
                max_age_hours=max_age_hours,
            )
        except Exception as e:
            last_err = str(e)
            continue
        for item in batch:
            key = _normalize_title(item.title)
            if key in seen_titles:
                continue
            seen_titles.add(key)
            merged.append(item)
            if len(merged) >= max_total:
                break
        if len(merged) >= max_total:
            break

    merged.sort(
        key=lambda x: _parse_published_at(x.published_at) or datetime.min,
        reverse=True,
    )
    return merged, last_err
