"""分批买入计划状态（供到期邮件提醒）。"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.config_loader import CONFIG_DIR

STATE_PATH = CONFIG_DIR / "batch_state.json"


def save_batch_state(
    start_date: date,
    budget_cny: float,
    batch_schedule: list[dict[str, Any]],
) -> Path:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "start_date": start_date.isoformat(),
        "budget_cny": budget_cny,
        "batch_schedule": batch_schedule,
        "sent_offsets": [],
        "updated_at": datetime.now().isoformat(),
    }
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return STATE_PATH


def load_batch_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def get_due_batch_today(today: date | None = None) -> dict[str, Any] | None:
    """若今日为某批执行日且未发送过，返回该批信息。"""
    state = load_batch_state()
    if not state:
        return None
    d = today or date.today()
    start = date.fromisoformat(state["start_date"])
    days = (d - start).days
    sent = set(state.get("sent_offsets") or [])

    for batch in state.get("batch_schedule") or []:
        if batch.get("batch") == "daily":
            continue
        offset = int(batch.get("day_offset", 0))
        if days == offset and offset not in sent:
            return {**batch, "day_offset": offset, "batch_num": batch.get("batch")}
    return None


def mark_batch_sent(day_offset: int) -> None:
    state = load_batch_state()
    if not state:
        return
    sent = list(set((state.get("sent_offsets") or []) + [day_offset]))
    state["sent_offsets"] = sent
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
