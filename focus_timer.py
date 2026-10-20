"""Account-local, shared focus timer state and restricted widget access.

Call read/control inside a BEGIN IMMEDIATE transaction so completion and timer
commands cannot race. Deadlines survive closed windows and server restarts.
"""

import hashlib
import json
import math
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone


def initialize(db):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS focus_timer (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS focus_widget_tokens (digest TEXT PRIMARY KEY, expires REAL NOT NULL);
    """)


def _fresh(minutes, title="", version=0):
    if type(minutes) is not int or not 1 <= minutes <= 240:
        raise ValueError("专注时长应为 1–240 分钟")
    if not isinstance(title, str) or len(title) > 120:
        raise ValueError("任务名称最多 120 字")
    return {"id": uuid.uuid4().hex, "title": title.strip(), "total": minutes * 60,
            "remaining": minutes * 60, "running": False, "deadline": 0,
            "completed": False, "version": version}


def _save(db, timer):
    db.execute("INSERT OR REPLACE INTO focus_timer VALUES (1, ?)", (json.dumps(timer),))
    return timer


def read(db, now=None):
    """Read the shared timer, recording an expired session exactly once."""
    now = time.time() * 1000 if now is None else now
    row = db.execute("SELECT value FROM focus_timer WHERE id=1").fetchone()
    if row:
        timer = json.loads(row["value"])
    else:
        settings = json.loads(db.execute("SELECT value FROM preferences WHERE id=1").fetchone()[0])
        timer = _save(db, _fresh(settings["focusMinutes"]))
    if timer["running"] and timer["deadline"] <= now:
        # Attribute completion to its actual Beijing deadline, even after an outage.
        day = datetime.fromtimestamp(timer["deadline"] / 1000, timezone(timedelta(hours=8))).date().isoformat()
        db.execute("INSERT OR IGNORE INTO focus VALUES (?, ?, ?)", (timer["id"], timer["total"], day))
        timer = _save(db, {**timer, "running": False, "remaining": 0,
                           "completed": True, "version": timer["version"] + 1})
    return timer


def control(db, payload, now=None):
    """Apply a command to the account's timer without silently replacing active work."""
    now = time.time() * 1000 if now is None else now
    timer = read(db, now)
    if not isinstance(payload, dict):
        raise ValueError("计时操作格式不正确")
    action = payload.get("action")
    if action not in ("start", "pause", "resume", "reset", "configure", "adopt"):
        raise ValueError("不支持的计时操作")
    expected = payload.get("expectedVersion")
    if expected is not None and (type(expected) is not int or expected != timer["version"]):
        raise ValueError("计时已有新变化，请刷新后重试")
    active = not timer["completed"] and (timer["running"] or timer["remaining"] < timer["total"])
    if action == "adopt":
        # Preserve unfinished browser timers when first moving to shared DDL state.
        if timer["version"] != 0:
            return timer
        saved = payload.get("timer", {})
        if not isinstance(saved, dict):
            raise ValueError("浏览器计时状态不正确")
        total, remaining, deadline = (saved.get(key) for key in ("total", "remaining", "deadline"))
        if (type(total) is not int or total % 60 or not 60 <= total <= 14400
                or type(remaining) not in (int, float) or not math.isfinite(remaining) or not 0 <= remaining <= total
                or type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline < 0
                or type(saved.get("running")) is not bool or not isinstance(saved.get("id"), str)
                or not 1 <= len(saved["id"]) <= 80):
            raise ValueError("浏览器计时状态不正确")
        if saved.get("completed") or remaining == 0:
            return timer
        timer = {**timer, "id": saved["id"], "total": total, "remaining": remaining,
                 "running": saved["running"], "deadline": deadline}
    elif action in ("start", "reset", "configure"):
        minutes = payload.get("durationMinutes", timer["total"] // 60)
        title = payload.get("title", timer["title"])
        fresh = _fresh(minutes, title, timer["version"])
        if action in ("start", "configure") and active:
            if action == "start" and fresh["total"] == timer["total"] and fresh["title"] == timer["title"]:
                if not timer["running"]:
                    timer.update(running=True, deadline=now + timer["remaining"] * 1000, version=timer["version"] + 1)
                    _save(db, timer)
                return timer
            raise ValueError("已有专注正在进行，请先暂停或重置当前计时")
        timer = fresh
        if action == "start":
            timer.update(running=True, deadline=now + timer["total"] * 1000)
        if action == "configure":
            settings = json.loads(db.execute("SELECT value FROM preferences WHERE id=1").fetchone()[0])
            settings["focusMinutes"] = minutes
            db.execute("UPDATE preferences SET value=? WHERE id=1", (json.dumps(settings),))
    elif action == "pause":
        if not timer["running"]:
            return timer
        timer.update(remaining=max(0, (timer["deadline"] - now) / 1000), running=False, deadline=0)
    elif action == "resume":
        if timer["completed"]:
            raise ValueError("本次专注已完成，请开始新的计时")
        if timer["running"]:
            return timer
        timer.update(running=True, deadline=now + timer["remaining"] * 1000)
    timer["version"] += 1
    _save(db, timer)
    return read(db, now)


def issue_token(db):
    """Create a 12-hour capability for the focus API only; persist its digest."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.execute("DELETE FROM focus_widget_tokens WHERE expires <= ?", (now,))
    db.execute("INSERT INTO focus_widget_tokens VALUES (?, ?)", (hashlib.sha256(token.encode()).hexdigest(), now + 43200))
    return token


def token_valid(db, token):
    if not isinstance(token, str) or not 20 <= len(token) <= 128:
        return False
    row = db.execute("SELECT expires FROM focus_widget_tokens WHERE digest=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    return bool(row and row["expires"] > time.time())
