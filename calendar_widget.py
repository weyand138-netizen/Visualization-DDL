"""Account-local read-only calendar capabilities and bounded event projection."""

import hashlib
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS calendar_widget_tokens (digest TEXT PRIMARY KEY, expires REAL NOT NULL)")


def issue_token(db):
    """Grant calendar reads for twelve hours without sharing account credentials."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.execute("DELETE FROM calendar_widget_tokens WHERE expires <= ?", (now,))
    db.execute("INSERT INTO calendar_widget_tokens VALUES (?, ?)",
               (hashlib.sha256(token.encode()).hexdigest(), now + 43200))
    return token


def token_valid(db, token):
    if not isinstance(token, str) or not re.fullmatch(r"[\w-]{20,128}", token, re.ASCII):
        return False
    row = db.execute("SELECT expires FROM calendar_widget_tokens WHERE digest=?",
                     (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    return bool(row and row["expires"] > time.time())


def read(db, account, query):
    """Read at most 42 inclusive calendar days, without reading other account data."""
    values = parse_qs(query, keep_blank_values=True)
    days = []
    for key in ("date_from", "date_to"):
        field = values.get(key, [])
        if len(field) != 1 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", field[0], re.ASCII):
            raise ValueError("日期范围请使用 YYYY-MM-DD")
        days.append(date.fromisoformat(field[0]))
    if not 0 <= (days[1] - days[0]).days <= 41:
        raise ValueError("日期范围应为顺序排列的 1 至 42 天")
    events = [dict(row) for row in db.execute(
        "SELECT * FROM events WHERE date >= ? AND date <= ? ORDER BY date, CASE WHEN time='' THEN 1 ELSE 0 END, time, createdAt, id",
        tuple(day.isoformat() for day in days))]
    return {"account": account, "timezone": "Asia/Shanghai",
            "beijingNow": datetime.now(timezone(timedelta(hours=8))).isoformat(), "events": events}
