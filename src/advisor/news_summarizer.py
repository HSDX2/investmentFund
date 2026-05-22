"""新闻标题 + LLM 一句话摘要。"""

from __future__ import annotations

import json
from pathlib import Path

from src.advisor.llm_client import chat_json, is_llm_configured
from src.collectors.news import NewsItem
from src.config_loader import ROOT

PROMPT_PATH = ROOT / "prompts" / "news_summarize_v1.txt"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def summarize_news_items(
    items: list[NewsItem],
    *,
    use_llm: bool = True,
) -> list[dict]:
    """为每条新闻生成一句话摘要，失败时回退为标题预览。"""
    if not items:
        return []

    base = [item.to_dict() for item in items]
    if not use_llm or not is_llm_configured():
        for row in base:
            row["summary"] = row.get("content_preview") or row["title"]
            row["summary_source"] = "preview"
        return base

    payload = [
        {
            "id": str(i),
            "keyword": it.keyword,
            "title": it.title,
            "published_at": it.published_at,
            "source": it.source,
            "content_preview": it.content_preview,
        }
        for i, it in enumerate(items)
    ]
    system = _load_prompt()
    user = (
        "请为以下新闻各写一句中文摘要（JSON 输出）：\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    try:
        parsed, _ = chat_json(system, user)
        summary_map = {
            str(row.get("id", "")): str(row.get("summary") or "").strip()
            for row in (parsed.get("items") or [])
        }
    except Exception:
        summary_map = {}

    out: list[dict] = []
    for i, item in enumerate(items):
        row = item.to_dict()
        summary = summary_map.get(str(i), "").strip()
        if summary:
            row["summary"] = summary[:80]
            row["summary_source"] = "llm"
        else:
            row["summary"] = row.get("content_preview") or row["title"]
            row["summary_source"] = "preview"
        out.append(row)
    return out


def build_news_digest(
    strategy: dict,
    positions: list[dict[str, str]],
    universe: list[dict[str, str]],
    *,
    use_llm: bool = True,
) -> tuple[list[dict], str | None]:
    """采集新闻并生成摘要 digest。"""
    from src.collectors.news import collect_news_items

    cfg = strategy.get("news") or {}
    if not cfg.get("enabled", False):
        return [], None

    items, fetch_err = collect_news_items(strategy, positions, universe)
    if not items:
        return [], fetch_err

    summarize = cfg.get("summarize", True)
    digest = summarize_news_items(items, use_llm=use_llm and summarize)
    return digest, fetch_err
