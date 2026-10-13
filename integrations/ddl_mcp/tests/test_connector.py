"""Exercise real HTTP/SQLite and the official MCP client with disposable data."""
import asyncio
import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import server as dashboard
from ddl_mcp.client import Config, DDLClient, DDLConnectionError, snapshot_version
from ddl_mcp.server import create_server
from mcp import Client
from mcp.client.stdio import StdioServerParameters


class QuietHandler(dashboard.Handler):
    def log_message(self, *args):
        pass


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_data = dashboard.DATA
        dashboard.DATA = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            'DDL_PASSWORD': 'fixture-admin-password', 'DDL_BOT_TOKEN': '', 'DDL_AI_URL': '',
            'DDL_USERS_JSON': json.dumps({'alice': {'passwordHash': dashboard.password_hash('fixture-alice-password')}}),
        })
        self.env.start()
        dashboard.initialize()
        self.http = dashboard.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.worker.start()
        self.base = f'http://127.0.0.1:{self.http.server_port}'
        self.config = Config(self.base, 'alice', 'fixture-alice-password')
        self.api = DDLClient(self.config)

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.worker.join()
        self.env.stop()
        dashboard.DATA = self.old_data
        self.temp.cleanup()

    def transport(self):
        return StdioServerParameters(command=sys.executable, args=['-m', 'ddl_mcp.server'],
            env={**os.environ, 'DDL_BASE_URL': self.base, 'DDL_USERNAME': 'alice',
                 'DDL_PASSWORD': 'fixture-alice-password'})

    @staticmethod
    def output(result):
        if result.is_error:
            raise AssertionError(str(result.content))
        return result.structured_content

    async def test_real_stdio_discovery_crud_partial_updates_and_validation(self):
        async with Client(self.transport()) as client:
            tools = await client.list_tools()
            self.assertEqual({item.name for item in tools.tools}, {
                'ddl_list_events', 'ddl_create_event', 'ddl_update_event', 'ddl_delete_event'})
            empty = self.output(await client.call_tool('ddl_list_events', {}))
            self.assertEqual(empty['events'], [])
            self.assertEqual(empty['timezone'], 'Asia/Shanghai')
            created = self.output(await client.call_tool('ddl_create_event', {'event': {
                'title': 'Demo delivery', 'date': '2030-04-15', 'notes': 'Synthetic fixture', 'incomeCents': 120000}}))
            event_id = created['results'][0]['event']['id']
            listed = self.output(await client.call_tool('ddl_list_events', {'query': 'delivery', 'date_from': '2030-04-01'}))
            event = listed['events'][0]
            self.assertNotIn('settings', listed)
            self.assertNotIn('focus', listed)
            self.assertNotIn('fixture-alice-password', json.dumps(listed))
            updated = self.output(await client.call_tool('ddl_update_event', {
                'event_id': event_id, 'expected_version': event['version'], 'changes': {'status': 'done', 'payment': 'paid'}}))
            self.assertEqual(updated['results'][0]['event']['title'], 'Demo delivery')
            self.assertEqual(updated['results'][0]['event']['incomeCents'], 120000)
            stale = await client.call_tool('ddl_delete_event', {'event_id': event_id, 'expected_version': event['version']})
            self.assertTrue(stale.is_error)
            invalid = await client.call_tool('ddl_create_event', {'event': {'title': 'Invalid', 'date': '2030-02-30'}})
            self.assertTrue(invalid.is_error)
            latest = self.output(await client.call_tool('ddl_list_events', {'status': 'done'}))['events'][0]
            deleted = self.output(await client.call_tool('ddl_delete_event', {'event_id': event_id, 'expected_version': latest['version']}))
            self.assertEqual(deleted['results'][0]['op'], 'delete')
            self.assertEqual(self.api.events(), [])
        with dashboard.connect('admin') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 0)

    async def test_wrong_credentials_and_account_mismatch_are_rejected(self):
        with self.assertRaisesRegex(DDLConnectionError, 'login failed'):
            DDLClient(Config(self.base, 'alice', 'wrong-fixture-password')).events()
        with patch.object(self.api, 'request', return_value={'account': {'id': 'admin'}, 'events': []}):
            with self.assertRaisesRegex(DDLConnectionError, 'unexpected account'):
                self.api.events()
        other = DDLClient(Config(self.base, 'admin', 'fixture-admin-password'))
        row = other.apply({'op': 'create', 'event': {'title': 'Other fixture', 'date': '2030-01-01', 'time': '',
            'category': 'work', 'status': 'planned', 'incomeCents': 0, 'payment': 'pending', 'notes': ''}})['results'][0]['event']
        with self.assertRaisesRegex(DDLConnectionError, 'missing or has changed'):
            self.api.current(row['id'], snapshot_version(row))

    async def test_http_retry_reuses_request_and_deduplicates_after_lost_reply(self):
        class LostReply:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, *args): raise TimeoutError()
        original = self.api.opener.open
        calls = []
        def open_once(req, **kwargs):
            calls.append(json.loads(req.data))
            response = original(req, **kwargs)
            if len(calls) == 1:
                response.read()
                response.close()
                return LostReply()
            return response
        action = {'op': 'create', 'event': {'title': 'Retry fixture', 'date': '2030-04-15', 'time': '',
            'category': 'work', 'status': 'planned', 'incomeCents': 0, 'payment': 'pending', 'notes': ''}}
        with patch.object(self.api.opener, 'open', side_effect=open_once):
            self.api.apply(action)
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(len(self.api.events()), 1)
        with patch.object(self.api.opener, 'open', side_effect=socket.timeout()):
            with self.assertRaisesRegex(DDLConnectionError, 'uncertain'):
                self.api.apply(action)

    async def test_direct_mcp_boundary_and_ai_capability(self):
        async with Client(create_server(self.api)) as client:
            data = self.output(await client.call_tool('ddl_list_events', {}))
            self.assertEqual(data['account'], 'alice')
        self.assertFalse(self.api.request('/api/state')['capabilities']['aiPlanning'])
        with patch.dict(os.environ, {'DDL_AI_URL': 'http://bridge.example', 'DDL_BOT_TOKEN': 'fixture-token'}):
            self.assertTrue(self.api.request('/api/state')['capabilities']['aiPlanning'])


class TransportSecurityTests(unittest.TestCase):
    def test_remote_http_embedded_credentials_and_invalid_accounts(self):
        for url in ('http://ddl.example.com', 'https://user:pass@ddl.example.com', 'https://ddl.example.com?x=1',
                    'https://ddl.example.com#fragment', 'file:///tmp/calendar'):
            with self.assertRaises(ValueError): Config(url, 'alice', 'fixture-password')
        for account in ('../admin', 'Alice', ''):
            with self.assertRaises(ValueError): Config('https://ddl.example.com', account, 'fixture-password')
        self.assertNotIn('fixture-password', repr(Config('https://ddl.example.com', 'alice', 'fixture-password')))

    def test_redirects_never_receive_credentials(self):
        hit = []
        class Target(dashboard.BaseHTTPRequestHandler):
            def do_GET(self):
                hit.append(self.headers.get('Authorization'))
                self.send_response(200); self.end_headers()
            def log_message(self, *args): pass
        target = dashboard.ThreadingHTTPServer(('127.0.0.1', 0), Target)
        class Redirect(Target):
            def do_GET(self):
                self.send_response(302)
                self.send_header('Location', f'http://127.0.0.1:{target.server_port}/')
                self.end_headers()
        redirect = dashboard.ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
        workers = [threading.Thread(target=item.serve_forever, daemon=True) for item in (target, redirect)]
        for worker in workers: worker.start()
        try:
            api = DDLClient(Config(f'http://127.0.0.1:{redirect.server_port}', 'alice', 'fixture-password'))
            with self.assertRaisesRegex(DDLConnectionError, 'redirects are refused'):
                api.events()
            self.assertEqual(hit, [])
        finally:
            for item in (target, redirect): item.shutdown(); item.server_close()
            for worker in workers: worker.join()


if __name__ == '__main__':
    unittest.main()
