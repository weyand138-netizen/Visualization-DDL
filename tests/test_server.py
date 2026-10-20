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
            db.execute("DELETE FROM focus_timer")
            db.execute("DELETE FROM focus_widget_tokens")
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

    def test_shared_timer_preserves_paused_time_and_records_completion_once(self):
        import focus_timer
        with patch.object(focus_timer.time, 'time', return_value=1893456000):
            status, value = self.request('/api/focus-timer', 'POST', {'action': 'start', 'durationMinutes': 1, 'title': 'Read'})
        self.assertEqual(status, 200)
        timer = value['timer']
        with patch.object(focus_timer.time, 'time', return_value=1893456001.25):
            paused = self.request('/api/focus-timer', 'POST', {'action': 'pause', 'expectedVersion': timer['version']})[1]['timer']
        self.assertEqual(paused['remaining'], 58.75)
        with patch.object(focus_timer.time, 'time', return_value=1893459600):
            resumed = self.request('/api/focus-timer', 'POST', {'action': 'resume', 'expectedVersion': paused['version']})[1]['timer']
        self.assertEqual(resumed['deadline'], 1893459658750)
        with patch.object(focus_timer.time, 'time', return_value=1893459660):
            with ThreadPoolExecutor(max_workers=4) as pool:
                states = list(pool.map(lambda _: self.request('/api/state')[1], range(4)))
        for state in states:
            self.assertTrue(state['focusTimer']['completed'])
            self.assertEqual(state['focusSessions'], [{'id': timer['id'], 'seconds': 60, 'date': '2030-01-01'}])

    def test_focus_commands_preserve_active_work_and_reject_stale_versions(self):
        timer = self.request('/api/focus-timer', 'POST', {'action': 'start', 'durationMinutes': 25})[1]['timer']
        self.assertEqual(self.request('/api/focus-timer', 'POST', {'action': 'start', 'durationMinutes': 50})[0], 400)
        self.assertEqual(self.request('/api/focus-timer', 'POST', {'action': 'reset', 'expectedVersion': 0})[0], 400)
        same = self.request('/api/focus-timer', 'POST', {'action': 'start', 'durationMinutes': 25})[1]['timer']
        self.assertEqual(same['id'], timer['id'])
        self.assertEqual(same['deadline'], timer['deadline'])
        for duration in (0, 241, 1.5, True):
            self.assertEqual(self.request('/api/focus-timer', 'POST', {'action': 'configure', 'durationMinutes': duration})[0], 400)

    def test_widget_capability_is_account_bound_and_cannot_read_calendar(self):
        accounts = json.dumps({'alice': {'passwordHash': server.password_hash('fixture-alice')}})
        with patch.dict(os.environ, {'DDL_PASSWORD': 'fixture-admin', 'DDL_USERS_JSON': accounts}):
            server.initialize_account('alice')
            login = {'Authorization': 'Basic ' + base64.b64encode(b'alice:fixture-alice').decode(), 'X-DDL-Account': 'alice'}
            status, value = self.request('/api/focus-widget-token', 'POST', {}, login)
            self.assertEqual(status, 200)
            restricted = {'Authorization': 'Bearer ' + value['token'], 'X-DDL-Account': 'alice'}
            self.assertEqual(self.request('/api/focus-timer', 'POST', {'action': 'start'}, restricted)[0], 200)
            self.assertEqual(self.request('/api/state', headers=restricted)[0], 401)
            self.assertEqual(self.request('/api/focus-widget-token', 'POST', {}, restricted)[0], 401)
            self.assertEqual(self.request('/api/focus-timer', headers={**restricted, 'X-DDL-Account': 'admin'})[0], 409)
            self.assertEqual(self.request('/focus-widget')[0], 200)
            with server.connect('alice') as db:
                db.execute('UPDATE focus_widget_tokens SET expires=0')
            self.assertEqual(self.request('/api/focus-timer', headers=restricted)[0], 401)
            with server.connect('admin') as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM focus_timer').fetchone()[0], 0)

    def test_calendar_widget_is_read_only_account_bound_and_range_limited(self):
        accounts = json.dumps({'calendar-user': {'passwordHash': server.password_hash('fixture-calendar')}})
        with patch.dict(os.environ, {'DDL_PASSWORD': 'fixture-admin', 'DDL_USERS_JSON': accounts}):
            server.initialize_account('calendar-user')
            login = {'Authorization': 'Basic ' + base64.b64encode(b'calendar-user:fixture-calendar').decode(),
                     'X-DDL-Account': 'calendar-user'}
            self.assertEqual(self.request('/api/events', 'POST', self.event(date='2032-02-29'), login)[0], 201)
            self.assertEqual(self.request('/api/events', 'POST', self.event(date='2032-04-01'), login)[0], 201)
            status, grant = self.request('/api/calendar-widget-token', 'POST', {}, login)
            self.assertEqual(status, 200)
            restricted = {'Authorization': 'Bearer ' + grant['token']}
            route = '/api/calendar-widget?date_from=2032-02-23&date_to=2032-04-04'
            status, value = self.request(route, headers=restricted)
            self.assertEqual(status, 200)
            self.assertEqual(value['account'], 'calendar-user')
            self.assertEqual(value['timezone'], 'Asia/Shanghai')
            self.assertEqual(len(value['events']), 2)
            self.assertEqual(set(value), {'account', 'timezone', 'beijingNow', 'events'})
            self.assertEqual(self.request(route, headers={**restricted, 'X-DDL-Account': 'admin'})[0], 409)
            for path in ('/api/state', '/api/focus-timer', '/api/calendar-widget-token', '/api/events'):
                self.assertEqual(self.request(path, headers=restricted)[0], 401)
            for method in ('POST', 'PUT', 'DELETE'):
                self.assertEqual(self.request(route, method, {}, restricted)[0], 401)
            for query in ('date_from=2032-02-30&date_to=2032-03-01', 'date_from=2032-03-01&date_to=2032-02-29',
                          'date_from=2032-01-01&date_to=2032-04-01', 'date_from=2032-01-01',
                          'date_from=2032-1-01&date_to=2032-01-02'):
                self.assertEqual(self.request('/api/calendar-widget?' + query, headers=restricted)[0], 400)
            with server.connect('calendar-user') as db:
                db.execute('UPDATE calendar_widget_tokens SET expires=0')
            self.assertEqual(self.request(route, headers=restricted)[0], 401)
            self.assertEqual(self.request('/calendar-widget')[0], 200)

    def test_calendar_widget_filters_dates_and_does_not_materialize_focus_state(self):
        self.request('/api/events', 'POST', self.event(date='2030-12-31'))
        self.request('/api/events', 'POST', self.event(date='2031-01-01'))
        self.request('/api/events', 'POST', self.event(date='2031-01-02'))
        status, value = self.request('/api/calendar-widget?date_from=2030-12-31&date_to=2031-01-01')
        self.assertEqual(status, 200)
        self.assertEqual([e['date'] for e in value['events']], ['2030-12-31', '2031-01-01'])
        with server.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM focus_timer').fetchone()[0], 0)

    def test_unfinished_browser_timer_is_adopted_only_before_shared_commands(self):
        saved = {'id': 'browser-session', 'total': 1500, 'remaining': 1000, 'running': False, 'deadline': 0}
        adopted = self.request('/api/focus-timer', 'POST', {'action': 'adopt', 'timer': saved})[1]['timer']
        self.assertEqual(adopted['id'], 'browser-session')
        self.assertEqual(adopted['remaining'], 1000)
        next_timer = self.request('/api/focus-timer', 'POST', {'action': 'adopt', 'timer': {**saved, 'id': 'other'}})[1]['timer']
        self.assertEqual(next_timer['id'], 'browser-session')

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
