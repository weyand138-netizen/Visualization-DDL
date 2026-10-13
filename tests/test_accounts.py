"""Verify account isolation over real HTTP, SQLite and the AI bridge boundary."""
import base64
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server
from test_server import QuietHandler

spec = importlib.util.spec_from_file_location('ddl_routing', Path(__file__).resolve().parents[1] / 'integrations/astrbot_plugin_ddl/routing.py')
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


class AccountTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hash = server.password_hash('second-password')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_data = server.DATA
        server.DATA = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {
            'DDL_PASSWORD': 'first-password', 'DDL_BOT_TOKEN': 'bot-secret', 'DDL_AI_URL': '',
            'DDL_USERS_JSON': json.dumps({'user2': {'passwordHash': self.hash, 'displayName': 'Second workspace'}}),
        })
        self.environment.start()
        server.initialize()
        self.http = server.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.worker.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown(); self.http.server_close(); self.worker.join()
        self.environment.stop(); server.DATA = self.original_data; self.temp.cleanup()

    def request(self, path, method='GET', value=None, account='admin', headers=None):
        password = {'admin': 'first-password', 'user2': 'second-password'}.get(account, 'invalid')
        authorization = 'Bearer bot-secret' if account == 'bot' else 'Basic ' + base64.b64encode(f'{account}:{password}'.encode()).decode()
        request = Request(self.base + path, method=method,
                          data=json.dumps(value).encode() if value is not None else None,
                          headers={'Authorization': authorization, 'Content-Type': 'application/json',
                                   **({'X-DDL-Account': account} if account == 'user2' else {}), **(headers or {})})
        try:
            response = urlopen(request, timeout=8)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None

    def event(self, title='first-private-event'):
        return {'title': title, 'date': '2026-10-12', 'time': '', 'category': 'work', 'status': 'planned',
                'incomeCents': 10000, 'payment': 'pending', 'notes': 'private notes'}

    def test_login_identity_and_account_header_cannot_escalate_access(self):
        self.assertEqual(self.request('/api/state')[1]['account']['id'], 'admin')
        self.assertEqual(self.request('/api/state', account='user2')[1]['account']['id'], 'user2')
        self.assertEqual(self.request('/api/state', account='missing')[0], 401)
        self.assertEqual(self.request('/api/state', account='user2', headers={'X-DDL-Account': 'admin'})[0], 409)
        self.assertEqual(self.request('/api/events', 'POST', self.event(), account='user2', headers={'X-DDL-Account': 'admin'})[0], 409)
        self.assertEqual(self.request('/api/focus', 'POST', {'id': 'old-page', 'seconds': 1500, 'date': '2026-10-12'}, account='user2', headers={'X-DDL-Account': ''})[0], 409)
        self.assertEqual(self.request('/api/state', account='user2')[1]['focusSessions'], [])
        self.assertEqual(self.request('/api/state')[1]['events'], [])
        self.assertFalse(server.password_matches('wrong-password', self.hash))

    def test_events_settings_focus_and_batch_request_ids_are_independent(self):
        _, first = self.request('/api/events', 'POST', self.event())
        _, second = self.request('/api/events', 'POST', self.event('second-private-event'), account='user2')
        self.assertEqual([item['id'] for item in self.request('/api/state')[1]['events']], [first['id']])
        self.assertEqual([item['id'] for item in self.request('/api/state', account='user2')[1]['events']], [second['id']])
        for method in ['PUT', 'DELETE']:
            self.assertEqual(self.request('/api/events/' + first['id'], method, self.event() if method == 'PUT' else None, account='user2')[0], 404)
        self.assertEqual(self.request('/api/settings', 'PUT', {**server.DEFAULT_SETTINGS, 'theme': 'dark', 'dailyFocusGoal': 75}, account='user2')[0], 200)
        self.assertEqual(self.request('/api/state')[1]['settings']['dailyFocusGoal'], 120)
        session = {'id': 'same-id', 'date': '2026-10-12', 'seconds': 1500}
        self.request('/api/focus', 'POST', session)
        self.request('/api/focus', 'POST', {**session, 'seconds': 600}, account='user2')
        self.assertEqual(self.request('/api/state')[1]['focusSessions'], [session])
        self.assertEqual(self.request('/api/state', account='user2')[1]['focusSessions'][0]['seconds'], 600)
        for account in ['admin', 'user2']:
            plan = {'requestId': 'same-request', 'actions': [{'op': 'create', 'event': self.event(account)}]}
            result = self.request('/api/events/batch', 'POST', plan, account=account)
            self.assertEqual(result[0], 200)
            self.assertEqual(self.request('/api/events/batch', 'POST', plan, account=account), result)
            self.assertEqual(len(self.request('/api/state', account=account)[1]['events']), 2)
        server.initialize()
        self.assertEqual(len(self.request('/api/state')[1]['events']), 2)
        self.assertEqual(len(self.request('/api/state', account='user2')[1]['events']), 2)

    def test_bot_reads_and_mutations_use_the_explicit_bound_account(self):
        _, first = self.request('/api/events', 'POST', self.event())
        second_headers = {'X-DDL-Account': 'user2'}
        self.assertEqual(self.request('/api/bot/events', account='bot', headers=second_headers)[1]['events'], [])
        self.assertEqual(len(self.request('/api/bot/events', account='bot')[1]['events']), 1)
        denied = {'requestId': 'attack', 'actions': [{'op': 'delete', 'id': first['id']}]}
        self.assertEqual(self.request('/api/bot/apply', 'POST', denied, account='bot', headers=second_headers)[0], 400)
        plan = {'requestId': 'qq-second', 'actions': [{'op': 'create', 'event': self.event('from QQ second')}]}
        self.assertEqual(self.request('/api/bot/apply', 'POST', plan, account='bot', headers=second_headers)[0], 200)
        self.assertEqual(len(self.request('/api/state', account='user2')[1]['events']), 1)
        self.assertEqual(len(self.request('/api/state')[1]['events']), 1)
        self.assertEqual(self.request('/api/bot/events', account='bot', headers={'X-DDL-Account': '../admin'})[0], 404)

    def test_ai_bridge_uses_authenticated_identity_instead_of_body_account(self):
        captured = []
        class BridgeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, *args): return b'{"reply":"ok","actions":[]}'
        def bridge(request, **kwargs):
            captured.append(dict((key.lower(), value) for key, value in request.header_items()))
            return BridgeResponse()
        with patch.dict(os.environ, {'DDL_AI_URL': 'http://bridge.test'}), patch.object(server, 'urlopen', bridge):
            self.assertEqual(self.request('/api/ai/plan', 'POST', {'text': 'query', 'account': 'admin'}, account='user2')[0], 200)
        self.assertEqual(captured[0]['x-ddl-account'], 'user2')

    def test_primary_database_stays_at_its_original_location(self):
        self.assertEqual(server.database_path(), server.DATA / 'dashboard.sqlite3')
        self.assertEqual(server.database_path('user2'), server.DATA / 'users/user2/dashboard.sqlite3')
        with self.assertRaises(ValueError): server.database_path('../admin')


class QQBindingTests(unittest.TestCase):
    def test_two_people_are_routed_to_different_accounts(self):
        allowed = ['1000000001', '1000000002']
        bindings = ['1000000001:admin', '1000000002:user2']
        self.assertEqual(routing.account_for_qq('1000000001', allowed, bindings), 'admin')
        self.assertEqual(routing.account_for_qq('1000000002', allowed, bindings), 'user2')
        self.assertIsNone(routing.account_for_qq('123456', allowed, bindings))
        self.assertIsNone(routing.account_for_qq('1000000002', allowed, bindings + ['1000000002:admin']))
        self.assertIsNone(routing.account_for_qq('1000000002', allowed, ['1000000002:../admin']))
        self.assertIsNone(routing.account_for_qq('1000000002', allowed, ['1000000001:admin']))
        self.assertEqual(routing.account_for_qq('1000000001', allowed, []), 'admin')
