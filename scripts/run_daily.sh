#!/usr/bin/env bash
# Linux 定时运行脚本（对应 Windows 的 run_daily.bat）
# 用法：由 cron 定时调用，或手动 bash scripts/run_daily.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$PROJECT_ROOT/logs"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/daily_${TODAY}.log"

mkdir -p "$LOG_DIR"

cd "$PROJECT_ROOT"
source .venv/bin/activate

echo "=== 基金日报任务开始: $(date) ===" >> "$LOG_FILE"

if python scripts/daily_report.py >> "$LOG_FILE" 2>&1; then
    echo "=== 任务完成: $(date) ===" >> "$LOG_FILE"
else
    echo "=== 任务失败: $(date) ===" >> "$LOG_FILE"
    python scripts/notify_failure.py >> "$LOG_FILE" 2>&1 || true
fi
