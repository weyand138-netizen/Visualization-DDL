"""Take a consistent SQLite backup and retain the latest fourteen copies."""
import subprocess
import json
import os
from datetime import datetime
from pathlib import Path

folder = Path(os.environ.get('DDL_BACKUP_DIR', '/var/backups/ddl-dashboard'))
container = os.environ.get('DDL_CONTAINER', 'visualization-ddl-ddl-1')
folder.mkdir(mode=0o700, parents=True, exist_ok=True)
code = """
import json, pathlib, re, sqlite3
root = pathlib.Path('/app/data')
result = []
for path in [root / 'dashboard.sqlite3', *root.glob('users/*/dashboard.sqlite3')]:
    account = 'admin' if path.parent == root else path.parent.name
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', account):
        continue
    target = path.parent / '.backup.sqlite3'
    src = sqlite3.connect(str(path)); dst = sqlite3.connect(str(target))
    src.backup(dst); dst.close(); src.close()
    result.append({'account': account, 'path': str(target)})
print(json.dumps(result))
"""
entries = json.loads(subprocess.check_output(['docker', 'exec', container, 'python', '-c', code]))
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
for entry in entries:
    prefix = 'ddl-' if entry['account'] == 'admin' else 'ddl-' + entry['account'] + '-'
    target = folder / (prefix + stamp + '.sqlite3')
    subprocess.run(['docker', 'cp', container + ':' + entry['path'], str(target)], check=True)
    target.chmod(0o600)
    candidates = sorted(path for path in folder.glob(prefix + '*.sqlite3')
                        if len(path.name.removeprefix(prefix)) == len('20261012-000000.sqlite3'))
    for stale in candidates[:-14]:
        stale.unlink()
    print('SQLite backup created:', target.name)
