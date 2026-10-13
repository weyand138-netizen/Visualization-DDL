"""Check source, tracked files, all Git objects, archives and Docker allowlist.

Reports only paths/rule names, never matching sensitive values. Add private known
markers via DDL_PRIVACY_DENY (newline separated); never commit that environment.
"""
import argparse
import ipaddress
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'server.py', 'package.json', 'Dockerfile', 'compose.yaml', '.env.example',
              '.gitignore', '.gitattributes', '.dockerignore', 'LICENSE', 'README.md', 'README.zh-CN.md',
              'PRIVACY.md', 'CONTRIBUTING.md'}
DIRECTORIES = {'public', 'tests', 'deploy', 'integrations', 'docs', 'tools', '.github'}
SKIP = {'.git', '.venv', '__pycache__', 'node_modules', 'dist', 'build', '.pytest_cache'}
BAD_SUFFIX = ('.db', '.sqlite', '.sqlite3', '-wal', '-shm', '.log', '.zip', '.tar', '.gz',
              '.pem', '.key', '.p12', '.pyc')
PATTERNS = {
    'credential token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{30,})'),
    'private key': re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----'),
    'personal Windows path': re.compile(rb'[A-Za-z]:[\\/](?:Users|test2)[\\/]', re.I),
    'personal Unix home': re.compile(rb'/home/(?!example(?:/|\b)|user(?:/|\b))[A-Za-z0-9_-]+/'),
}


def allowed(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and '..' not in path.parts and
            (name in ROOT_FILES or len(path.parts) > 1 and path.parts[0] in DIRECTORIES) and
            not any(part in SKIP or part in {'data', 'backups', '.ssh'} or part.endswith('.egg-info') for part in path.parts) and
            not name.lower().endswith(BAD_SUFFIX) and
            not (path.name.startswith('.env') and path.name != '.env.example'))


def inspect(name, raw):
    problems = []
    if not allowed(name):
        problems.append((name, 'outside source allowlist'))
    if b'\x00' in raw[:4096] or name.endswith(('.png', '.jpg', '.webp')):
        # Binary assets are generated from disposable data and visually reviewed.
        # Known markers and token signatures are still scanned below.
        text = False
    else:
        text = True
    for label, pattern in PATTERNS.items():
        if pattern.search(raw):
            problems.append((name, label))
    for marker in os.environ.get('DDL_PRIVACY_DENY', '').splitlines():
        if marker and marker.encode() in raw:
            problems.append((name, 'private deny marker'))
    if text:
        for candidate in re.findall(rb'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])', raw):
            try:
                address = ipaddress.ip_address(candidate.decode())
            except ValueError:
                continue
            if not (address.is_loopback or address.is_unspecified or
                    any(address in ipaddress.ip_network(net) for net in ('192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24'))):
                problems.append((name, 'non-example IPv4 address'))
    return problems


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], stderr=subprocess.DEVNULL)


def source_files():
    for name in ROOT_FILES:
        if (ROOT / name).is_file():
            yield ROOT / name
    for name in DIRECTORIES:
        base = ROOT / name
        if base.exists():
            for directory, subdirs, files in os.walk(base):
                subdirs[:] = [part for part in subdirs if part not in SKIP and not part.endswith('.egg-info')]
                for filename in files:
                    if not filename.endswith('.pyc'):
                        yield Path(directory) / filename


def archive_check(path):
    problems = []
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            name = entry.filename
            # Release archives use one fixed top-level source directory.
            prefix = 'Visualization-DDL/'
            if not name.startswith(prefix) or entry.is_dir():
                problems.append((name, 'invalid archive member'))
                continue
            problems.extend(inspect(name[len(prefix):], archive.read(entry)))
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--history', action='store_true')
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    problems = []
    files = list(source_files())
    for path in files:
        problems.extend(inspect(path.relative_to(ROOT).as_posix(), path.read_bytes()))
    try:
        tracked = git('ls-files', '-z').decode().split('\0')
    except subprocess.CalledProcessError:
        tracked = []
        if args.history:
            problems.append(('Git', 'history check requires initialized repository'))
    for name in filter(None, tracked):
        if not allowed(name):
            problems.append((name, 'tracked private/non-source file'))
    if args.history and tracked:
        for line in git('rev-list', '--objects', '--all').decode().splitlines():
            oid, _, name = line.partition(' ')
            kind = git('cat-file', '-t', oid).strip()
            raw = git('cat-file', '-p', oid)
            if kind == b'blob':
                problems.extend(inspect(name, raw))
            elif kind in (b'commit', b'tag'):
                for label, pattern in PATTERNS.items():
                    if pattern.search(raw): problems.append(('Git metadata', label))
                for marker in os.environ.get('DDL_PRIVACY_DENY', '').splitlines():
                    if marker and marker.encode() in raw: problems.append(('Git metadata', 'private deny marker'))
                if kind == b'commit':
                    for email in re.findall(rb'^(?:author|committer) .* <([^>]+)>', raw, re.M):
                        # GitHub-authored web commits use a platform noreply
                        # committer; their author must still pass this check.
                        if email != b'noreply@github.com' and not email.endswith(b'@users.noreply.github.com'):
                            problems.append(('Git metadata', 'non-noreply commit email'))
    expected = '**\n!Dockerfile\n!server.py\n!public/\n!public/**'
    if (ROOT / '.dockerignore').read_text().strip() != expected:
        problems.append(('.dockerignore', 'Docker context allowlist changed; review required'))
    if args.archive:
        problems.extend(archive_check(args.archive))
    if problems:
        for name, rule in sorted(set(problems)):
            print(f'FAIL {name}: {rule}')
        return 1
    print(f'Privacy checks passed ({len(files)} source files; tracked files, Docker context' +
          (', Git history' if args.history else '') + (', archive' if args.archive else '') + ').')
    return 0


if __name__ == '__main__':
    sys.exit(main())
