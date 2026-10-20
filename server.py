"""Serve the personal DDL dashboard and its SQLite API, with no third-party runtime dependencies."""

import base64
import binascii
import hmac
import hashlib
import json
import os
import re
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import focus_timer
import calendar_widget

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("DDL_DATA_DIR", str(ROOT / "data")))
DEFAULT_SETTINGS = {
    "theme": "light",
    "custom": {"button": "#486950", "background": "#f5f4ef", "border": "#dedfd5"},
    "focusMinutes": 25,
    "dailyFocusGoal": 120,
}


def configured_accounts():
    value = json.loads(os.environ.get("DDL_USERS_JSON") or "{}")
    if not isinstance(value, dict):
        raise ValueError("独立账户配置不正确")
    for name, account in value.items():
        if (name == "admin" or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", name)
                or not isinstance(account, dict) or not isinstance(account.get("passwordHash"), str)):
            raise ValueError("独立账户配置不正确")
    return value


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000).hex()
    return f"pbkdf2_sha256:260000:{salt}:{digest}"


def password_matches(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split(":")
        if algorithm != "pbkdf2_sha256" or not 200000 <= int(iterations) <= 1000000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def database_path(account="admin"):
    if not isinstance(account, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", account):
        raise ValueError("账户标识不正确")
    directory = DATA if account == "admin" else DATA / "users" / account
    return directory / "dashboard.sqlite3"


@contextmanager
def connect(account="admin"):
    db = sqlite3.connect(database_path(account), timeout=15)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    for account in ["admin", *configured_accounts()]:
        initialize_account(account)


def initialize_account(account):
    database_path(account).parent.mkdir(parents=True, exist_ok=True)
    with connect(account) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, date TEXT NOT NULL,
                time TEXT NOT NULL, category TEXT NOT NULL, status TEXT NOT NULL,
                incomeCents INTEGER NOT NULL, payment TEXT NOT NULL,
                notes TEXT NOT NULL, createdAt TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS focus (
                id TEXT PRIMARY KEY, seconds INTEGER NOT NULL, date TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bot_requests (
                id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL
            );
        """)
        db.execute("INSERT OR IGNORE INTO preferences VALUES (1, ?)", (json.dumps(DEFAULT_SETTINGS),))
        focus_timer.initialize(db)
        calendar_widget.initialize(db)
        settings = json.loads(db.execute("SELECT value FROM preferences WHERE id=1").fetchone()[0])
        if "dailyFocusGoal" not in settings:
            settings["dailyFocusGoal"] = 120
            db.execute("UPDATE preferences SET value=? WHERE id=1", (json.dumps(settings),))


def validate_event(value):
    if not isinstance(value, dict):
        raise ValueError("日程格式不正确")
    title = value.get("title", "")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120:
        raise ValueError("请输入 1–120 字的日程标题")
    day = value.get("date", "")
    if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("日期格式不正确")
    date.fromisoformat(day)
    time = value.get("time", "")
    if not isinstance(time, str) or (time and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time)):
        raise ValueError("时间格式不正确")
    cents = value.get("incomeCents", 0)
    if type(cents) is not int or not 0 <= cents <= 99999999999:
        raise ValueError("收入金额超出范围")
    for key, options in [("category", ["work", "personal", "study"]),
                         ("status", ["planned", "active", "done"]),
                         ("payment", ["pending", "paid"])]:
        if value.get(key) not in options:
            raise ValueError("日程分类或状态不正确")
    notes = value.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 10000:
        raise ValueError("详细说明最多 10000 字")
    return {"title": title.strip(), "date": day, "time": time,
            "category": value["category"], "status": value["status"],
            "incomeCents": cents, "payment": value["payment"], "notes": notes}


def validate_settings(value, default_goal=120):
    if not isinstance(value, dict) or value.get("theme") not in ["light", "dark", "custom"]:
        raise ValueError("主题设置不正确")
    custom = value.get("custom")
    if not isinstance(custom, dict) or any(
        not isinstance(custom.get(key), str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", custom[key])
        for key in ["button", "background", "border"]
    ):
        raise ValueError("请使用有效的十六进制颜色")
    minutes = value.get("focusMinutes")
    if type(minutes) is not int or not 1 <= minutes <= 240:
        raise ValueError("专注时长应为 1–240 分钟")
    goal = value.get("dailyFocusGoal", default_goal)
    if type(goal) is not int or not 1 <= goal <= 1440:
        raise ValueError("每日专注目标应为 1–1440 分钟")
    return {"theme": value["theme"], "custom": {k: custom[k] for k in ["button", "background", "border"]},
            "focusMinutes": minutes, "dailyFocusGoal": goal}


class Handler(BaseHTTPRequestHandler):
    server_version = "DDL/1.0"

    def send(self, status, value, content_type="application/json; charset=utf-8"):
        raw = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, (dict, list)) else value
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        widget = urlsplit(self.path).path in ("/focus-widget", "/calendar-widget")
        if not widget:
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer" if widget else "same-origin")
        ancestors = "'self' file: http://localhost:* http://127.0.0.1:*" if widget else "'none'"
        self.send_header("Content-Security-Policy", f"default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors {ancestors}; base-uri 'self'; form-action 'self'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def authorized(self):
        path = urlsplit(self.path).path
        accounts = configured_accounts()
        self.account_id = "admin"
        if path in ("/focus-widget", "/focus-widget.js", "/focus-widget.css", "/calendar-widget", "/calendar-widget.js",
                    "/calendar-widget.css", "/widget.css", "/widget.js", "/calendar-view.js", "/domain.js") and self.command in ("GET", "HEAD"):
            return True
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer ") and path == "/api/calendar-widget" and self.command in ("GET", "HEAD"):
            for account in ["admin", *accounts]:
                with connect(account) as db:
                    if calendar_widget.token_valid(db, authorization[7:]):
                        self.account_id = account
                        return self.account_matches()
            self.send(401, {"error": "日历连接已失效，请从 AIRI 重新打开"})
            return False
        if authorization.startswith("Bearer ") and path == "/api/focus-timer":
            for account in ["admin", *accounts]:
                with connect(account) as db:
                    if focus_timer.token_valid(db, authorization[7:]):
                        self.account_id = account
                        return self.account_matches()
            self.discard_request_body()
            self.send(401, {"error": "计时器连接已失效，请从 AIRI 重新打开"})
            return False
        if path.startswith("/api/bot/"):
            token = os.environ.get("DDL_BOT_TOKEN", "")
            provided = self.headers.get("Authorization", "")
            if token and hmac.compare_digest(provided.encode(), ("Bearer " + token).encode()):
                self.account_id = self.headers.get("X-DDL-Account", "admin")
                if self.account_id != "admin" and self.account_id not in accounts:
                    self.discard_request_body()
                    self.send(404, {"error": "账户不存在"})
                    return False
                return True
            self.discard_request_body()
            self.send(401, {"error": "机器人凭据无效"})
            return False
        if authorization.startswith("Bearer "):
            self.discard_request_body()
            self.send(401, {"error": "此凭证不允许访问该接口"})
            return False
        password = os.environ.get("DDL_PASSWORD", "")
        if not password and not accounts:
            return self.account_matches()
        try:
            scheme, token = self.headers.get("Authorization", "").split(" ", 1)
            decoded = base64.b64decode(token, validate=True).decode()
            user, provided = decoded.split(":", 1)
            primary = user == "admin" and bool(password) and hmac.compare_digest(provided.encode(), password.encode())
            secondary = user in accounts and password_matches(provided, accounts[user]["passwordHash"])
            if scheme.lower() == "basic" and (primary or secondary):
                self.account_id = user
                return self.account_matches()
        except (ValueError, UnicodeError, binascii.Error):
            pass
        self.discard_request_body()
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="DDL", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def account_matches(self):
        expected = self.headers.get("X-DDL-Account")
        legacy_secondary_write = (self.account_id != "admin" and self.command in ("POST", "PUT", "DELETE")
                                  and expected != self.account_id)
        if (expected and expected != self.account_id) or legacy_secondary_write:
            self.discard_request_body()
            self.send(409, {"error": "登录账户已切换，请刷新页面", "accountMismatch": True})
            return False
        return True

    def discard_request_body(self):
        # Drain small rejected writes before closing, so clients receive the
        # authorization response instead of a connection reset on Windows.
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if self.command in ("POST", "PUT", "DELETE") and 0 < size <= 65536:
                self.rfile.read(size)
        except ValueError:
            pass

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        limit = 8 * 1024 * 1024 if urlsplit(self.path).path == "/api/ai/plan" else 65536
        if not 0 < size <= limit:
            raise ValueError("请求内容为空或过大")
        raw = self.rfile.read(size)
        # Only same-origin browser mutations are accepted; non-browser CLI requests have no Origin.
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            raise ValueError("不允许跨站请求")
        return json.loads(raw)

    def handle_request(self):
        if not self.authorized():
            return
        path = urlsplit(self.path).path
        method = "GET" if self.command == "HEAD" else self.command
        try:
            if path == "/api/calendar-widget" and method == "GET":
                with connect(self.account_id) as db:
                    value = calendar_widget.read(db, self.account_id, urlsplit(self.path).query)
                self.send(200, value)
                return
            if path == "/api/calendar-widget-token" and method == "POST":
                self.read_json()
                with connect(self.account_id) as db:
                    token = calendar_widget.issue_token(db)
                self.send(200, {"account": self.account_id, "token": token})
                return
            if path == "/api/focus-timer" and method in ("GET", "POST"):
                payload = self.read_json() if method == "POST" else None
                with connect(self.account_id) as db:
                    db.execute("BEGIN IMMEDIATE")
                    timer = focus_timer.control(db, payload) if payload is not None else focus_timer.read(db)
                self.send(200, {"account": self.account_id, "timer": timer})
                return
            if path == "/api/focus-widget-token" and method == "POST":
                self.read_json()
                with connect(self.account_id) as db:
                    token = focus_timer.issue_token(db)
                self.send(200, {"token": token})
                return
            if method == "POST" and path == "/api/ai/plan":
                value = self.read_json()
                bridge = os.environ.get("DDL_AI_URL", "").rstrip('/')
                if not bridge or not os.environ.get("DDL_BOT_TOKEN"):
                    self.send(503, {"error": "AI尚未连接，请先配置AstrBot日程插件"})
                    return
                request = Request(bridge + '/plan', data=json.dumps(value).encode(),
                                  headers={"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["DDL_BOT_TOKEN"],
                                           "X-DDL-Account": self.account_id})
                try:
                    with urlopen(request, timeout=155) as response:
                        self.send(200, json.loads(response.read(65536)))
                except (HTTPError, URLError, TimeoutError, OSError):
                    self.send(503, {"error": "AI服务暂时不可用，请检查AstrBot模型连接后重试"})
                return
            if method == "GET" and path == "/api/bot/events":
                with connect(self.account_id) as db:
                    self.send(200, {"events": [dict(row) for row in db.execute("SELECT * FROM events ORDER BY date, time, createdAt")]})
                return
            if method == "POST" and path in ("/api/bot/apply", "/api/events/batch"):
                payload = self.read_json()
                if not isinstance(payload, dict) or not isinstance(payload.get("requestId"), str) or not re.fullmatch(r"[a-zA-Z0-9:_-]{1,128}", payload["requestId"]):
                    raise ValueError("机器人请求编号不正确")
                actions = payload.get("actions")
                if not isinstance(actions, list) or not 1 <= len(actions) <= 30:
                    raise ValueError("每次可处理 1–30 条日程")
                digest = hashlib.sha256(json.dumps(actions, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                # One transaction validates the entire plan and prevents replayed QQ messages.
                with connect(self.account_id) as db:
                    db.execute("BEGIN IMMEDIATE")
                    prior = db.execute("SELECT digest, result FROM bot_requests WHERE id=?", (payload["requestId"],)).fetchone()
                    if prior:
                        if prior["digest"] != digest:
                            raise ValueError("同一请求编号不能用于不同操作")
                        self.send(200, json.loads(prior["result"]))
                        return
                    result = []
                    for action in actions:
                        if not isinstance(action, dict) or action.get("op") not in ("create", "update", "delete"):
                            raise ValueError("日程操作不正确")
                        op = action["op"]
                        if op == "create":
                            event = {"id": uuid.uuid4().hex, **validate_event(action.get("event")), "createdAt": datetime.now(timezone.utc).isoformat()}
                            db.execute("INSERT INTO events VALUES (:id, :title, :date, :time, :category, :status, :incomeCents, :payment, :notes, :createdAt)", event)
                        else:
                            event_id = action.get("id")
                            if not isinstance(event_id, str) or not re.fullmatch(r"[0-9a-f]{32}", event_id):
                                raise ValueError("日程编号不正确")
                            row = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
                            if not row:
                                raise ValueError("要修改的日程已不存在，请重新查询")
                            event = dict(row)
                            if "expected" in action and action["expected"] != event:
                                raise ValueError("这条日程已有新修改，请重新整理后保存")
                            if op == "delete":
                                db.execute("DELETE FROM events WHERE id=?", (event_id,))
                            else:
                                event.update(validate_event(action.get("event")))
                                db.execute("UPDATE events SET title=:title, date=:date, time=:time, category=:category, status=:status, incomeCents=:incomeCents, payment=:payment, notes=:notes WHERE id=:id", event)
                        result.append({"op": op, "event": event})
                    response = {"results": result}
                    db.execute("INSERT INTO bot_requests VALUES (?, ?, ?)", (payload["requestId"], digest, json.dumps(response, ensure_ascii=False)))
                self.send(200, response)
                return
            if method == "GET" and path == "/api/state":
                with connect(self.account_id) as db:
                    db.execute("BEGIN IMMEDIATE")
                    timer = focus_timer.read(db)
                    self.send(200, {"capabilities": {"aiPlanning": bool(os.environ.get("DDL_AI_URL") and os.environ.get("DDL_BOT_TOKEN"))},
                                    "focusTimer": timer,
                                    "account": {"id": self.account_id, "displayName": configured_accounts().get(self.account_id, {}).get("displayName", "我的日常")},
                                    "events": [dict(row) for row in db.execute("SELECT * FROM events ORDER BY date, time, createdAt")],
                                    "settings": json.loads(db.execute("SELECT value FROM preferences WHERE id = 1").fetchone()[0]),
                                    "focusSessions": [dict(row) for row in db.execute("SELECT id, seconds, date FROM focus ORDER BY date, id")],
                                    "focus": [dict(row) for row in db.execute("SELECT date, SUM(seconds) AS seconds, COUNT(*) AS sessions FROM focus GROUP BY date")]})
                return
            if path == "/api/settings" and method == "PUT":
                payload = self.read_json()
                with connect(self.account_id) as db:
                    current = json.loads(db.execute("SELECT value FROM preferences WHERE id=1").fetchone()[0])
                    value = validate_settings(payload, current.get("dailyFocusGoal", 120))
                    db.execute("UPDATE preferences SET value = ? WHERE id = 1", (json.dumps(value),))
                self.send(200, value)
                return
            if path == "/api/focus" and method == "POST":
                value = self.read_json()
                if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not 1 <= len(value["id"]) <= 80:
                    raise ValueError("专注记录格式不正确")
                if type(value.get("seconds")) is not int or not 60 <= value["seconds"] <= 14400:
                    raise ValueError("专注时间超出范围")
                day = value.get("date", "")
                if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                    raise ValueError("专注日期不正确")
                date.fromisoformat(day)
                # The client retries completed sessions after outages; ids prevent double counting.
                with connect(self.account_id) as db:
                    db.execute("INSERT OR IGNORE INTO focus VALUES (?, ?, ?)", (value["id"], value["seconds"], day))
                self.send(200, {"ok": True})
                return
            if path == "/api/events" and method == "POST":
                value = validate_event(self.read_json())
                event = {"id": uuid.uuid4().hex, **value, "createdAt": datetime.now(timezone.utc).isoformat()}
                with connect(self.account_id) as db:
                    db.execute("INSERT INTO events VALUES (:id, :title, :date, :time, :category, :status, :incomeCents, :payment, :notes, :createdAt)", event)
                self.send(201, event)
                return
            match = re.fullmatch(r"/api/events/([0-9a-f]{32})", path)
            if match and method in ["PUT", "DELETE"]:
                value = validate_event(self.read_json()) if method == "PUT" else None
                if method == "DELETE" and self.headers.get("Origin") and urlsplit(self.headers["Origin"]).netloc != self.headers.get("Host"):
                    raise ValueError("不允许跨站请求")
                with connect(self.account_id) as db:
                    if not db.execute("SELECT id FROM events WHERE id = ?", (match[1],)).fetchone():
                        self.send(404, {"error": "这条日程已不存在"})
                        return
                    if value:
                        db.execute("UPDATE events SET title=:title, date=:date, time=:time, category=:category, status=:status, incomeCents=:incomeCents, payment=:payment, notes=:notes WHERE id=:id", {**value, "id": match[1]})
                    else:
                        db.execute("DELETE FROM events WHERE id = ?", (match[1],))
                self.send(200, {"ok": True})
                return
            assets = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
                      "/focus-widget": ("focus-widget.html", "text/html"),
                      "/focus-widget.js": ("focus-widget.js", "text/javascript"),
                      "/focus-widget.css": ("focus-widget.css", "text/css"),
                      "/calendar-widget": ("calendar-widget.html", "text/html"),
                      "/calendar-widget.js": ("calendar-widget.js", "text/javascript"),
                      "/calendar-widget.css": ("calendar-widget.css", "text/css"),
                      "/calendar-view.js": ("calendar-view.js", "text/javascript"),
                      "/widget.css": ("widget.css", "text/css"), "/widget.js": ("widget.js", "text/javascript"),
                      "/app.js": ("app.js", "text/javascript"), "/domain.js": ("domain.js", "text/javascript"),
                      "/focus-store.js": ("focus-store.js", "text/javascript"),
                      "/account-store.js": ("account-store.js", "text/javascript"),
                      "/style.css": ("style.css", "text/css"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
            if method == "GET" and path in assets:
                file, mime = assets[path]
                self.send(200, (ROOT / "public" / file).read_bytes(), mime + "; charset=utf-8")
                return
            self.send(404, {"error": "未找到内容"})
        except (ValueError, TypeError, OverflowError) as error:
            self.send(400, {"error": str(error) or "请求格式不正确"})
        except sqlite3.Error:
            self.send(503, {"error": "数据暂时无法保存，请稍后重试"})

    do_GET = handle_request
    do_HEAD = handle_request
    do_POST = handle_request
    do_PUT = handle_request
    do_DELETE = handle_request


if __name__ == "__main__":
    initialize()
    host = os.environ.get("DDL_HOST", "127.0.0.1")
    port = int(os.environ.get("DDL_PORT", "8080"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"DDL dashboard: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
