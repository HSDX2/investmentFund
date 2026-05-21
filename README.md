# 投资基金自动化交易

AI 辅助的基金推荐、每日涨跌总结、加减仓/换基建议，并逐步支持半自动/自动执行。

## 文档

- [建设方案（必读）](docs/投资基金自动化交易系统方案.md)
- [项目进度与变更记录](docs/项目进度与变更记录.md) — **下次开发先看此文件**

## 配置

- `config/strategy.yaml` — 风险偏好与交易模式
- `config/fund_universe.csv` — AI 可推荐的基金候选池
- `config/positions.csv` — 当前持仓

## 快速开始（Phase 1）

```bash
cd d:\visual\makeMoney\investmentFund
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/daily_report.py
```

报告输出到 `reports/YYYY-MM-DD.md`。强制刷新净值缓存：

```bash
python scripts/daily_report.py --no-cache
```

## Phase 2（AI 建议）

1. 复制环境变量：`copy .env.example .env`（PowerShell）
2. 在 `.env` 填入 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`（支持 DeepSeek / OpenAI 兼容接口）
3. 安装新依赖：`pip install -r requirements.txt`
4. 运行：

```bash
python scripts/daily_report.py
```

仅规则扫描、不调用 LLM：

```bash
python scripts/daily_report.py --no-ai
```

AI 建议审计 JSON：`data/advice/YYYY-MM-DD.json`

## Phase 3（QQ 邮件推送 + 操作清单）

1. 在 [QQ 邮箱](https://mail.qq.com) → 设置 → 账户 → 开启 SMTP，生成**授权码**
2. 在 `.env` 中配置（见 `.env.example`）：
   - `SMTP_USER=346157791@qq.com`
   - `SMTP_PASSWORD=授权码`
   - `NOTIFY_TO=346157791@qq.com`
3. 运行 `python scripts/daily_report.py`，将发送 HTML 邮件并生成本地操作清单 `data/checklist/YYYY-MM-DD.md`
4. 不发电邮：`python scripts/daily_report.py --no-email`

收件人可在 `config/notify.yaml` 的 `email.to` 修改。

## 定时任务

### GitHub Actions（推荐）

项目已配置 GitHub Actions 工作流，每天北京时间 **20:35** 自动运行日报并推送邮件。

**配置步骤**：在 GitHub 仓库 → Settings → Secrets and variables → Actions 中添加以下 Secrets：

| Secret | 必填 | 说明 |
|--------|------|------|
| `LLM_API_KEY` | 是 | DeepSeek / OpenAI 兼容 API Key |
| `LLM_BASE_URL` | 否 | 默认 `https://api.deepseek.com` |
| `LLM_MODEL` | 否 | 默认 `deepseek-chat` |
| `SMTP_USER` | 是 | QQ 邮箱地址（如 `346157791@qq.com`） |
| `SMTP_PASSWORD` | 是 | QQ 邮箱 SMTP 授权码 |
| `NOTIFY_TO` | 是 | 收件人邮箱 |

配置完成后，工作流将每天自动执行。也可在 Actions 页面手动触发（`workflow_dispatch`）。

任务失败时自动发送告警邮件；报告和建议 JSON 保存为 GitHub Artifacts（保留 30 天）。

### Linux（cron）

```bash
# 手动运行（写日志到 logs/）
bash scripts/run_daily.sh

# 注册 cron：每天 UTC 12:35（北京时间 20:35）
crontab -e
35 12 * * * /path/to/scripts/run_daily.sh
```

### Windows（任务计划程序）

```powershell
# 注册：每天 20:35 自动跑日报+发邮件
powershell -ExecutionPolicy Bypass -File scripts\register_scheduled_task.ps1

# 立即试跑
schtasks /Run /TN "InvestmentFundDailyReport"

# 手动运行（写日志到 logs/）
scripts\run_daily.bat

# 删除任务
powershell -File scripts\unregister_scheduled_task.ps1
```

任务失败时会尝试发送告警邮件；日志见 `logs/daily_YYYY-MM-DD.log`。

## 策略说明

`config/strategy.yaml` 已按当前持仓校准：市值 &lt; 1 万元时不触发单基/主题仓位告警；`270042` 为仅定投。市值上万后自动启用 80% 上限检查。

## 建议实施顺序

1. 填写上述配置  
2. **Phase 1**：净值同步 + 每日 Markdown 报告  
3. **Phase 2**：规则扫描 + AI 总结与加减仓建议  
4. **Phase 3**（当前）：操作清单 + QQ 邮件推送（`semi_auto`，需在 APP 手动下单）  
5. Phase 4：全自动（视券商 API 而定）
