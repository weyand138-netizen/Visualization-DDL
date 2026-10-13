"""Local-only disposable visual fixtures; never reads the user's database.

Run: python tests/visual_qa_server.py --port 8083 --control data/visual-qa-control.json
Write {"blockFocus": true} to the control file to test a disconnected write path.
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8083)
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--empty', action='store_true')
    parser.add_argument('--accounts', action='store_true')
    args = parser.parse_args()
    os.environ['DDL_PASSWORD'] = ''
    os.environ['DDL_BOT_TOKEN'] = ''
    os.environ['DDL_USERS_JSON'] = (json.dumps({'user2': {'passwordHash': server.password_hash('visual-test-only'),
                                                        'displayName': '第二位使用人'}}) if args.accounts else '')
    args.control.write_text('{}', encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='ddl-visual-') as directory:
        server.DATA = Path(directory)
        server.initialize()
        today = datetime.now(timezone(timedelta(hours=8))).date()
        with server.connect() as db:
            for offset, durations in ([] if args.empty else [(0, [1500] * 3), (1, [7200]), (2, [9000]), (6, [14400] * 3 + [10500])]):
                for index, seconds in enumerate(durations):
                    db.execute('INSERT INTO focus(id, seconds, date) VALUES(?,?,?)',
                               (f'fixture-{offset}-{index}', seconds, str(today - timedelta(days=offset))))
            event = {'id': 'visual-event', 'title': '整理设计方案', 'date': str(today), 'time': '14:00',
                     'category': 'work', 'status': 'planned', 'incomeCents': 80000,
                     'payment': 'pending', 'notes': '检查日历渐变下的文字与点击操作。', 'createdAt': datetime.now().isoformat()}
            if not args.empty:
                db.execute('INSERT INTO events VALUES (:id, :title, :date, :time, :category, :status, :incomeCents, :payment, :notes, :createdAt)', event)
                for index, (title, offset, category, status) in enumerate([
                    ('演示：阅读计划', 1, 'study', 'planned'),
                    ('演示：周末散步', 3, 'personal', 'planned'),
                    ('演示：完成设计初稿', -1, 'work', 'done'),
                ]):
                    demo = {**event, 'id': f'demo-{index}', 'title': title,
                            'date': str(today + timedelta(days=offset)), 'category': category,
                            'status': status, 'incomeCents': 0, 'notes': '公开演示数据，不属于真实用户。'}
                    db.execute('INSERT INTO events VALUES (:id, :title, :date, :time, :category, :status, :incomeCents, :payment, :notes, :createdAt)', demo)

        class VisualHandler(server.Handler):
            def authorized(self):
                if not args.accounts:
                    return super().authorized()
                try:
                    control = json.loads(args.control.read_text(encoding='utf-8-sig'))
                except (OSError, ValueError):
                    control = {}
                self.account_id = control.get('activeAccount', 'admin')
                if self.account_id not in ('admin', 'user2'):
                    return False
                return self.account_matches()

            def handle_request(self):
                try:
                    control = json.loads(args.control.read_text(encoding='utf-8-sig'))
                except (OSError, ValueError):
                    control = {}
                if control.get('blockFocus') and self.path == '/api/focus' and self.command == 'POST':
                    self.rfile.read(int(self.headers.get('Content-Length', '0')))
                    return self.send(503, {'error': 'Visual QA: focus temporarily offline'})
                return super().handle_request()

            def log_message(self, *args):
                pass

            do_GET = handle_request
            do_HEAD = handle_request
            do_POST = handle_request
            do_PUT = handle_request
            do_DELETE = handle_request

        print(f'Visual QA: http://127.0.0.1:{args.port}/; fixture date {today}', flush=True)
        class ExclusiveServer(server.ThreadingHTTPServer):
            allow_reuse_address = False

        ExclusiveServer(('127.0.0.1', args.port), VisualHandler).serve_forever()


if __name__ == '__main__':
    main()
