"""Exercise the real HTTP and SQLite boundary using a disposable database."""

import base64
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class QuietHandler(server.Handler):
    def log_message(self, *args):
        pass


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.original_data = server.DATA
        server.DATA = Path(cls.temp.name)
        cls.environment = patch.dict(os.environ, {"DDL_PASSWORD": "", "DDL_BOT_TOKEN": "", "DDL_AI_URL": ""})
        cls.environment.start()
        server.initialize()
        cls.http = server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.worker = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.worker.start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.worker.join()
        cls.environment.stop()
        server.DATA = cls.original_data
        cls.temp.cleanup()

    def setUp(self):
        with server.connect() as db:
            db.execute("DELETE FROM events")
            db.execute("DELETE FROM focus")
            db.execute("DELETE FROM bot_requests")
            db.execute("UPDATE preferences SET value=?", (json.dumps(server.DEFAULT_SETTINGS),))

    def request(self, path, method="GET", value=None, headers=None):
        raw = json.dumps(value).encode() if value is not None else None
        req = Request(self.base + path, data=raw, method=method,
                      headers={"Content-Type": "application/json", **(headers or {})})
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            if "application/json" in response.headers.get("Content-Type", ""):
                body = json.loads(body)
            return response.status, body

    def event(self, **changes):
        return {"title": "交付设计初稿", "date": "2026-10-10", "time": "14:30", "category": "work",
                "status": "planned", "incomeCents": 120005, "payment": "pending", "notes": "含两轮修改", **changes}

    def test_event_create_edit_persist_and_delete(self):
        status, created = self.request("/api/events", "POST", self.event())
        self.assertEqual(status, 201)
        path = f"/api/events/{created['id']}"
        status, _ = self.request(path, "PUT", self.event(status="done", payment="paid"))
        self.assertEqual(status, 200)
        server.initialize()
        status, state = self.request("/api/state")
        self.assertEqual(state["events"][0]["payment"], "paid")
        self.assertEqual(state["events"][0]["incomeCents"], 120005)
        self.assertEqual(state["events"][0]["notes"], "含两轮修改")
        self.assertEqual(self.request(path, "DELETE")[0], 200)
        self.assertEqual(self.request("/api/state")[1]["events"], [])
        self.assertEqual(self.request(path, "DELETE")[0], 404)

    def test_invalid_dates_times_amounts_and_shapes_are_rejected(self):
        for invalid in [self.event(date="2026-02-29"), self.event(date="2026-1-01"), self.event(time="25:30"),
                        self.event(incomeCents=0.1), self.event(incomeCents=True), self.event(incomeCents=-1),
                        self.event(title=" "), self.event(category="other"), self.event(notes="x" * 10001), []]:
            with self.subTest(invalid=str(invalid)[:80]):
                self.assertEqual(self.request("/api/events", "POST", invalid)[0], 400)
        self.assertEqual(self.request("/api/state")[1]["events"], [])

    def test_custom_colors_survive_switching_to_default_themes(self):
        settings = {"theme": "custom", "custom": {"button": "#123456", "background": "#222222", "border": "#555555"}, "focusMinutes": 47, "dailyFocusGoal": 120}
        self.assertEqual(self.request("/api/settings", "PUT", settings)[0], 200)
        settings["theme"] = "dark"
        self.assertEqual(self.request("/api/settings", "PUT", settings)[0], 200)
        self.assertEqual(self.request("/api/state")[1]["settings"], settings)
        self.assertEqual(self.request("/api/settings", "PUT", {**settings, "focusMinutes": 0})[0], 400)
        self.assertEqual(self.request("/api/settings", "PUT", {**settings, "custom": {}})[0], 400)

    def test_focus_retries_and_concurrent_tabs_do_not_double_count(self):
        session = {"id": "same-session", "seconds": 1500, "date": "2026-10-10"}
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: self.request("/api/focus", "POST", session)[0], range(6)))
        self.assertEqual(results, [200] * 6)
        self.assertEqual(self.request("/api/focus", "POST", session)[0], 200)
        server.initialize()
        self.assertEqual(self.request("/api/state")[1]["focus"], [{"date": "2026-10-10", "seconds": 1500, "sessions": 1}])
        self.assertEqual(self.request("/api/state")[1]["focusSessions"], [session])
        self.assertEqual(self.request("/api/focus", "POST", {**session, "seconds": 1800})[0], 200)
        self.assertEqual(self.request("/api/state")[1]["focusSessions"], [session])
        self.assertEqual(self.request("/api/focus", "POST", {**session, "seconds": 59})[0], 400)

    def test_daily_goal_migration_validation_and_legacy_updates(self):
        legacy = {key: value for key, value in server.DEFAULT_SETTINGS.items() if key != "dailyFocusGoal"}
        with server.connect() as db:
            db.execute("UPDATE preferences SET value=?", (json.dumps(legacy),))
        server.initialize()
        self.assertEqual(self.request("/api/state")[1]["settings"]["dailyFocusGoal"], 120)
        for goal in (1, 75, 1440):
            settings = {**legacy, "dailyFocusGoal": goal}
            self.assertEqual(self.request("/api/settings", "PUT", settings)[0], 200)
            self.assertEqual(self.request("/api/settings", "PUT", {**legacy, "focusMinutes": 47})[0], 200)
            saved = self.request("/api/state")[1]["settings"]
            self.assertEqual(saved["dailyFocusGoal"], goal)
            self.assertEqual(saved["focusMinutes"], 47)
        for invalid in (0, 1441, True, 1.5, "120", None):
            self.assertEqual(self.request("/api/settings", "PUT", {**legacy, "dailyFocusGoal": invalid})[0], 400)

    def test_cross_origin_writes_are_rejected(self):
        self.assertEqual(self.request("/api/events", "POST", self.event(), {"Origin": "https://other.example"})[0], 400)
        self.assertEqual(self.request("/api/state")[1]["events"], [])

    def test_optional_password_protects_api_and_page(self):
        with patch.dict(os.environ, {"DDL_PASSWORD": "test-pass"}):
            self.assertEqual(self.request("/api/state")[0], 401)
            self.assertEqual(self.request("/")[0], 401)
            self.assertEqual(self.request("/", "HEAD")[0], 401)
            token = base64.b64encode(b"admin:test-pass").decode()
            self.assertEqual(self.request("/api/state", headers={"Authorization": "Basic " + token})[0], 200)
            self.assertEqual(self.request("/api/state", headers={"Authorization": "Basic invalid!"})[0], 401)

    def test_only_declared_public_assets_are_served(self):
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/app.js")[0], 200)
        self.assertEqual(self.request("/focus-store.js")[0], 200)
        self.assertEqual(self.request("/server.py")[0], 404)
        self.assertEqual(self.request("/data/dashboard.sqlite3")[0], 404)

    def test_bot_token_is_required_and_cannot_access_page_or_settings(self):
        with patch.dict(os.environ, {"DDL_PASSWORD": "test-pass", "DDL_BOT_TOKEN": "bot-secret"}):
            bot = {"Authorization": "Bearer bot-secret"}
            basic = {"Authorization": "Basic " + base64.b64encode(b"admin:test-pass").decode()}
            self.assertEqual(self.request("/api/bot/events")[0], 401)
            self.assertEqual(self.request("/api/bot/events", headers=basic)[0], 401)
            self.assertEqual(self.request("/api/bot/events", headers=bot), (200, {"events": []}))
            self.assertEqual(self.request("/api/state", headers=bot)[0], 401)
            self.assertEqual(self.request("/api/settings", "PUT", server.DEFAULT_SETTINGS, bot)[0], 401)
        self.assertEqual(self.request("/api/bot/events", headers={"Authorization": "Bearer "})[0], 401)

    def test_bot_batch_is_atomic_and_replay_is_idempotent(self):
        with patch.dict(os.environ, {"DDL_BOT_TOKEN": "bot-secret"}):
            headers = {"Authorization": "Bearer bot-secret"}
            payload = {"requestId": "qq-message-1", "actions": [{"op": "create", "event": self.event()}]}
            status, saved = self.request("/api/bot/apply", "POST", payload, headers)
            self.assertEqual(status, 200)
            self.assertEqual(self.request("/api/bot/apply", "POST", payload, headers), (200, saved))
            self.assertEqual(len(self.request("/api/bot/events", headers=headers)[1]["events"]), 1)
            changed = {**payload, "actions": [{"op": "create", "event": self.event(title="不应重复写入")}]}
            self.assertEqual(self.request("/api/bot/apply", "POST", changed, headers)[0], 400)
            invalid = {"requestId": "qq-message-2", "actions": payload["actions"] + [{"op": "update", "id": "0" * 32, "event": self.event()}]}
            self.assertEqual(self.request("/api/bot/apply", "POST", invalid, headers)[0], 400)
            self.assertEqual(len(self.request("/api/bot/events", headers=headers)[1]["events"]), 1)
            event_id = saved["results"][0]["event"]["id"]
            updates = {"requestId": "qq-message-3", "actions": [{"op": "update", "id": event_id, "event": self.event(status="done")}]}
            self.assertEqual(self.request("/api/bot/apply", "POST", updates, headers)[1]["results"][0]["event"]["status"], "done")
            deletion = {"requestId": "qq-message-4", "actions": [{"op": "delete", "id": event_id}]}
            self.assertEqual(self.request("/api/bot/apply", "POST", deletion, headers)[0], 200)
            self.assertEqual(self.request("/api/bot/apply", "POST", deletion, headers)[0], 200)

    def test_web_batch_and_unconfigured_ai(self):
        payload = {"requestId": "web-review-1", "actions": [{"op": "create", "event": self.event()}]}
        self.assertEqual(self.request("/api/events/batch", "POST", payload, {"Origin": "https://other.example"})[0], 400)
        self.assertEqual(self.request("/api/events/batch", "POST", payload)[0], 200)
        self.assertEqual(self.request("/api/ai/plan", "POST", {"text": "明天下午3点开会"})[0], 503)

    def test_ai_update_cannot_overwrite_changes_made_after_preview(self):
        _, original = self.request("/api/events", "POST", self.event())
        self.request('/api/events/' + original['id'], 'PUT', self.event(notes='Updated after preview'))
        payload = {'requestId': 'stale-plan', 'actions': [{'op': 'update', 'id': original['id'], 'expected': original, 'event': self.event(status='done')}]}
        self.assertEqual(self.request('/api/events/batch', 'POST', payload)[0], 400)
        event = self.request('/api/state')[1]['events'][0]
        self.assertEqual(event['notes'], 'Updated after preview')
        self.assertEqual(event['status'], 'planned')


if __name__ == "__main__":
    unittest.main()
