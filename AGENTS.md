# AGENTS.md

## Cursor Cloud specific instructions

### 项目概述

这是一个 **AI 辅助的基金投资日报系统**（Python CLI），用于中国 A 股基金的每日净值同步、持仓分析、规则扫描、AI 建议和邮件推送。没有 Web 服务、数据库或 Docker — 是纯 Python 脚本应用。

### 运行方式

- **入口脚本**: `python scripts/daily_report.py`
- 常用参数:
  - `--no-ai` — 不调用 LLM，仅数据+规则扫描
  - `--no-email` — 不发送邮件
  - `--no-cache` — 忽略本地净值缓存，强制重新拉取
- 在 Cloud Agent 环境中，由于没有 LLM API Key 和邮箱授权码，请使用 `--no-ai --no-email` 运行
- 运行前需要激活 venv: `source .venv/bin/activate`

### 依赖安装

虚拟环境和依赖由 update script 自动管理（`python3 -m venv .venv` + `pip install -r requirements.txt`）。需要 `python3.12-venv` 系统包（已安装）。

### Lint / Type Check

项目无内置 lint 配置，可用 `ruff` 和 `pyright` 手动检查：
- `ruff check src/ scripts/` — 已知 `E402` 警告在 `scripts/daily_report.py` 中属正常（`sys.path` 修改在 import 之前）
- `pyright src/ scripts/` — 已知 akshare 类型提示不完整会报 2 个 error，属上游问题

### 测试

当前项目无自动化测试。验证方式为运行主脚本并检查输出文件：
- 报告: `reports/YYYY-MM-DD.md`
- 审计 JSON: `data/advice/YYYY-MM-DD.json`
- 操作清单: `data/checklist/YYYY-MM-DD.md`

### 注意事项

- 净值数据通过 AkShare 从东方财富获取，需要网络访问（无需 API Key）
- 首次运行会从网络拉取基金净值并缓存到 `data/nav/`，缓存 TTL 为 1 小时
- 配置文件在 `config/` 目录下（`strategy.yaml`, `positions.csv`, `fund_universe.csv`）
- `.env` 文件从 `.env.example` 复制而来，包含 LLM 和邮件配置
