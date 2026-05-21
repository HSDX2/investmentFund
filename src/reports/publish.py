"""将 Markdown 报告发布为可浏览 HTML（GitHub Pages / docs/reports）。"""

from __future__ import annotations

import os
from pathlib import Path

import markdown

from src.config_loader import ROOT

DOCS_REPORTS = ROOT / "docs" / "reports"
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: "Microsoft YaHei", sans-serif; line-height: 1.65; color: #222;
            max-width: 920px; margin: 24px auto; padding: 0 16px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #f5f5f5; }}
    blockquote {{ background: #f8f8f8; border-left: 4px solid #ccc; margin: 12px 0; padding: 8px 12px; }}
    h1, h2, h3 {{ margin-top: 1.2em; }}
    pre {{ background: #f7f7f7; padding: 12px; overflow: auto; }}
  </style>
</head>
<body>
{body}
<p style="color:#888;font-size:12px;margin-top:32px">不构成投资建议 · 数据仅供参考</p>
</body>
</html>
"""


def get_public_base_url() -> str | None:
    base = (os.getenv("REPORT_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    return base or None


def public_report_url(report_date: str, kind: str = "daily") -> str | None:
    base = get_public_base_url()
    if not base:
        return None
    if kind == "fund-recommend":
        return f"{base}/reports/fund-recommend-{report_date}.html"
    return f"{base}/reports/{report_date}.html"


def markdown_to_html_page(md_text: str, title: str) -> str:
    body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    return HTML_TEMPLATE.format(title=title, body=body)


def publish_markdown_report(
    md_text: str,
    report_date: str,
    *,
    kind: str = "daily",
    title: str | None = None,
) -> tuple[Path, Path, str | None]:
    """写入 docs/reports/*.html 与 *.md，返回 (html_path, md_path, public_url)。"""
    DOCS_REPORTS.mkdir(parents=True, exist_ok=True)
    stem = f"fund-recommend-{report_date}" if kind == "fund-recommend" else report_date

    title = title or f"基金报告 {report_date}"
    html_path = DOCS_REPORTS / f"{stem}.html"
    md_path = DOCS_REPORTS / f"{stem}.md"

    html_path.write_text(markdown_to_html_page(md_text, title), encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")

    return html_path, md_path, public_report_url(report_date, kind=kind)


def footer_report_lines(public_url: str | None) -> tuple[str, str]:
    """返回 (plain_footer, html_footer)。"""
    if public_url:
        plain = f"完整报告（点击打开）：{public_url}\n（也可打开邮件附件中的 HTML 文件）"
        html_f = (
            f'<p style="margin-top:20px">'
            f'<a href="{public_url}" style="font-size:16px;color:#0969da;font-weight:bold">'
            f"📊 点击查看完整报告</a></p>"
            f'<p style="color:#888;font-size:12px">或打开邮件附件：基金日报.html</p>'
        )
    else:
        plain = "完整报告见邮件附件「基金日报.html」，下载后用浏览器打开。"
        html_f = (
            '<p style="margin-top:16px">'
            "完整报告见邮件附件 <b>基金日报.html</b>，下载后用浏览器打开。</p>"
        )
    return plain, html_f
