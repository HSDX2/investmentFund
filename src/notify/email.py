"""通过 QQ 邮箱 SMTP 推送日报与操作清单。"""

from __future__ import annotations

import html
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Iterable

from src.executor.checklist import OperationItem
from src.notify.settings import EmailSettings

EmailAttachment = tuple[str, str, str]  # filename, content, mime_subtype e.g. html

ACTION_LABELS = {
    "hold": "持有",
    "add": "加仓",
    "reduce": "减仓",
    "switch": "换基",
}


def _checklist_rows_html(items: list[OperationItem]) -> str:
    if not items:
        return "<p>今日无明确操作，建议持有观望。</p>"
    rows = []
    for op in items:
        label = ACTION_LABELS.get(op.action, op.action)
        detail = "<br>".join(html.escape(s) for s in op.steps)
        extra = []
        if op.ratio is not None:
            extra.append(f"比例 {op.ratio * 100:.0f}%")
        if op.shares is not None:
            extra.append(f"约 {op.shares} 份")
        if op.amount_cny is not None:
            extra.append(f"约 {op.amount_cny:,.2f} 元")
        extra_s = "；".join(extra) if extra else "—"
        rows.append(
            f"<tr><td>{html.escape(op.fund_code)}</td>"
            f"<td>{html.escape(op.fund_name)}</td>"
            f"<td>{html.escape(op.channel)}</td>"
            f"<td><b>{html.escape(label)}</b></td>"
            f"<td>{html.escape(extra_s)}</td>"
            f"<td style='font-size:13px'>{detail}</td></tr>"
        )
    return (
        "<table border='1' cellpadding='8' cellspacing='0' "
        "style='border-collapse:collapse;width:100%;font-size:14px'>"
        "<tr style='background:#f0f0f0'>"
        "<th>代码</th><th>名称</th><th>渠道</th><th>操作</th><th>估算</th><th>步骤</th>"
        "</tr>"
        + "".join(rows)
        + "</table>"
    )


def build_email_bodies(
    report_date: str,
    report_markdown: str,
    checklist_items: list[OperationItem],
    market_summary: str,
    portfolio_total: float,
    portfolio_pnl: float,
    portfolio_pnl_pct: float,
) -> tuple[str, str]:
    """返回 (plain_text, html)。"""
    summary = market_summary or "（无 AI 摘要，请查看规则扫描与持仓数据）"
    text_parts = [
        f"基金日报 {report_date}",
        "",
        f"账户市值：{portfolio_total:,.2f} 元",
        f"浮动盈亏：{portfolio_pnl:+,.2f} 元（{portfolio_pnl_pct:+.2f}%）",
        "",
        "【AI 摘要】",
        summary,
        "",
        "【今日操作清单】",
    ]
    if not checklist_items:
        text_parts.append("今日无明确操作。")
    else:
        for i, op in enumerate(checklist_items, 1):
            label = ACTION_LABELS.get(op.action, op.action)
            text_parts.append(f"{i}. {label} {op.fund_name}({op.fund_code}) @ {op.channel}")
            for step in op.steps:
                text_parts.append(f"   {step}")
            text_parts.append("")

    text_parts.extend(
        [
            "---",
            "完整 Markdown 日报见本地 reports 目录。",
            "semi_auto：请在 APP 手动确认后执行，不构成投资建议。",
        ]
    )
    plain = "\n".join(text_parts)

    report_pre = html.escape(report_markdown[:12000])
    if len(report_markdown) > 12000:
        report_pre += "\n…（正文过长，请查看本地 reports 文件）"

    html_body = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:Microsoft YaHei,sans-serif;line-height:1.6;color:#222">
  <h2>基金日报 {html.escape(report_date)}</h2>
  <p>
    <b>账户市值</b>：{portfolio_total:,.2f} 元<br>
    <b>浮动盈亏</b>：{portfolio_pnl:+,.2f} 元（{portfolio_pnl_pct:+.2f}%）
  </p>
  <h3>AI 摘要</h3>
  <p>{html.escape(summary).replace(chr(10), '<br>')}</p>
  <h3>今日操作清单（请在 APP 手动执行）</h3>
  {_checklist_rows_html(checklist_items)}
  <h3>完整日报</h3>
  <pre style="background:#f7f7f7;padding:12px;overflow:auto;font-size:12px">{report_pre}</pre>
  <p style="color:#888;font-size:12px">semi_auto 模式 · 系统不会自动下单 · 不构成投资建议</p>
</body></html>"""
    return plain, html_body


def send_email(
    settings: EmailSettings,
    subject: str,
    plain_body: str,
    html_body: str,
    *,
    to_addrs: Iterable[str] | None = None,
    attachments: list[EmailAttachment] | None = None,
) -> None:
    if not settings.is_ready:
        raise RuntimeError(
            "邮件未就绪：请在 .env 配置 SMTP_USER、SMTP_PASSWORD（QQ 邮箱授权码）、NOTIFY_TO"
        )

    recipients = list(to_addrs) if to_addrs else [settings.notify_to]
    msg = MIMEMultipart("mixed")
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(plain_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    for filename, content, subtype in attachments or []:
        part = MIMEBase("text", subtype, charset="utf-8")
        part.set_payload(content.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=("utf-8", "", filename),
        )
        msg.attach(part)

    msg["Subject"] = subject
    msg["From"] = settings.smtp_user
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port) as server:
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(settings.smtp_user, recipients, msg.as_string())
