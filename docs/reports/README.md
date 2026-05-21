# 在线报告（GitHub Pages）

启用 GitHub Pages：**Settings → Pages → Build from branch `main` → Folder `/docs`**

报告 URL 示例：

- 日报：`https://stj8888.github.io/investmentFund/reports/2026-05-21.html`
- 选基：`https://stj8888.github.io/investmentFund/reports/fund-recommend-2026-05-21.html`

在 `.env` 设置：

```env
REPORT_PUBLIC_BASE_URL=https://stj8888.github.io/investmentFund
```

邮件底部将显示可点击链接；同时附带 HTML 附件作为备用。
