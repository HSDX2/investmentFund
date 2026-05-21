# Cursor 本地 Agent vs Cloud Agent 协作方案

> 适用：投资基金项目已上 GitHub，本地 Windows 开发 + Cloud Agent 远程开发并存。  
> 最后更新：2026-05-21

---

## 一、先记住分工（一句话）

| 场景 | 用哪里 |
|------|--------|
| 要跑脚本、测邮件、注册计划任务、改 `.env` | **本地对话框（本机 Agent）** |
| 要写功能、改多文件、开 PR、人不在电脑旁 | **Cloud Agent（云端对话框）** |
| 定需求、看方案、决定做不做 Phase 4 | **本地对话框**（或任意，但结论写进文档） |

**不要指望 Cloud Agent 替你验证 QQ 邮件和 Windows 定时任务**——它没有你的 `.env` 和本机环境。

---

## 二、两个对话框各自擅长什么

### 本地 Agent（你现在这个对话框）

- 直接读写 `d:\visual\makeMoney\investmentFund`
- 能执行 `python scripts/daily_report.py`、`run_daily.bat`、`schtasks`
- 能读 **`.env`**（LLM Key、QQ 授权码）并真实发邮件
- 适合 AkShare 拉净值（走你本机网络）
- 适合调试「为什么今天邮件没收到」

### Cloud Agent（Cursor 云端）

- 从 **GitHub 仓库** clone 分支，在云端改代码
- 适合：新功能、重构、补测试、写文档、开 **Pull Request**
- 异步跑，你可以关电脑
- **一般没有** 你的 `.env`、不能替你跑 Windows 计划任务
- 合并前需要在本地 **pull + 跑一遍** 验证

---

## 三、推荐工作流（GitHub 已接入后）

```
你定需求（本地聊清楚 或 写 Issue）
        ↓
┌───────────────────┬───────────────────────┐
│ 纯代码/文档/PR     │ 要本机验证             │
│ → Cloud Agent     │ → 本地 Agent           │
└─────────┬─────────┴───────────┬───────────┘
          │                     │
          ▼                     ▼
    云端 push 分支 / 开 PR    直接改 main 或同步 PR
          │                     │
          └──────────┬──────────┘
                     ▼
          本地 git pull → 跑 daily_report → 看邮件/日志
                     ▼
          更新 docs/项目进度与变更记录.md
```

---

## 四、你怎么「下命令」（模板）

### 给 Cloud Agent 的开场（复制改仓库 URL）

```text
仓库：<你的 GitHub org/repo>
请先读 docs/项目进度与变更记录.md 和 README.md。

任务：<具体功能，例如「邮件正文只发摘要+操作清单，完整日报不要塞进 HTML」>
约束：
- 不要提交 .env
- 保持 semi_auto，不做 Phase 4 自动下单
- 改完说明如何本地验证
- 开 PR 到 main
```

### 给本地 Agent 的开场（本对话框）

```text
我已从 GitHub pull 最新代码。
请先读 docs/项目进度与变更记录.md。

任务：<例如「跑一遍 daily_report 并确认邮件」「注册/检查计划任务」>
.env 已配置好，可直接测。
```

### 需求较大时（推荐）

1. **本地** 先聊 5 分钟：要不要做、边界是什么  
2. 把结论 **写进** `docs/项目进度与变更记录.md` 第十节或开 GitHub Issue  
3. **Cloud** 实现 + PR  
4. **本地** pull、测试、合并  

---

## 五、按任务类型选对话框

| 任务 | 建议 |
|------|------|
| 新 Phase 功能（Web 看板、跟踪 CSV） | Cloud 开发 → 本地验证 |
| 修 AkShare / 指数 / 规则 / Prompt | Cloud 改代码 → **本地跑** `--no-email` 看报告 |
| QQ 邮件、SMTP、邮件模板 | Cloud 改 `src/notify/` → **本地** 真发一封 |
| Windows `schtasks`、`.bat` | **本地 Agent**（Cloud 只能改脚本，不能替你注册） |
| 改 `strategy.yaml` / csv 持仓 | 本地改（含隐私）→ 可选 **不要 push 持仓** |
| 写方案、复盘、下次做什么 | 本地或 Cloud 都行 → **必须更新 docs** |
| 紧急：今晚邮件没发 | **只找本地 Agent** |

---

## 六、Git 与隐私（必做）

### 不要提交 GitHub 的文件

- `.env`（LLM Key、QQ 授权码）
- `data/`、`logs/`（缓存与日志）
- 若持仓敏感：可用 `config/positions.csv.example`，真实 `positions.csv` 仅本地

确认 `.gitignore` 已包含：

```
.env
data/
logs/
```

### 分支习惯

| 谁改 | 分支 |
|------|------|
| Cloud Agent | `feat/xxx` 或 Agent 自动分支 → PR |
| 本地小改 | `main` 或 `fix/xxx` |
| 合并前 | 本地 `git pull` → `python scripts/daily_report.py --no-email` |

---

## 七、Cloud Agent 合并后本地必做清单

```powershell
cd d:\visual\makeMoney\investmentFund
git pull
pip install -r requirements.txt
python scripts/daily_report.py --no-email
# 可选：真发邮件
python scripts/daily_report.py
# 若改了 bat / 计划任务
scripts\run_daily.bat
```

通过后再 `git push` 你的本地配置（若有文档更新）。

---

## 八、避免混乱的三条规则

1. **单一事实来源**：`docs/项目进度与变更记录.md` — 两边 Agent 都先读它。  
2. **代码走 GitHub**：Cloud 的改动不要只在云端；本地不要长期「和 GitHub 各改各的」而不 pull。  
3. **验证在本地**：凡涉及邮件、定时任务、真实净值，以本机跑通为准。

---

## 九、针对本项目的默认策略（建议你就按这个来）

| 你想… | 指挥方式 |
|--------|----------|
| 日常「今晚有没有邮件、持仓对不对」 | **本地对话框** |
| 加功能、改架构、写 PR | **Cloud Agent** + 本地合并验证 |
| 和 AI 讨论策略参数、要不要减仓 | **本地**（顺便改 `strategy.yaml`） |
| 出差/睡觉让 AI 写代码 | **Cloud Agent**，醒来本地 pull 测试 |

---

## 十、下次开场白（固定句式）

**本地继续时：**

> 投资基金项目，GitHub 已同步。先读 `docs/项目进度与变更记录.md`，然后帮我：……

**Cloud 开发时：**

> 投资基金项目 repo: `<url>`，先读 `docs/项目进度与变更记录.md` 和 `docs/Cursor协作开发方案.md`，在分支上实现：……

---

*与 [项目进度与变更记录.md](./项目进度与变更记录.md) 配套使用。*
