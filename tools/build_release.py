"""Build a deterministic source-only ZIP from a clean, checked Git checkout."""
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path
from privacy_check import ROOT, allowed, archive_check


def main():
    subprocess.run([sys.executable, str(ROOT / 'tools/privacy_check.py'), '--history'], check=True)
    if subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain']).strip():
        raise SystemExit('Commit reviewed source changes before building a release.')
    files = subprocess.check_output(['git', '-C', str(ROOT), 'ls-files', '-z']).decode().split('\0')
    output = ROOT / 'dist/Visualization-DDL-v1.1.0-source.zip'
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(filter(None, files)):
            if not allowed(name):
                raise SystemExit('Non-source tracked path: ' + name)
            entry = zipfile.ZipInfo('Visualization-DDL/' + name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, (ROOT / name).read_bytes())
    if archive_check(output):
        raise SystemExit('Archive privacy validation failed')
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix('.zip.sha256').write_text(digest + '  ' + output.name + '\n', encoding='ascii')
    print(output.name + ' SHA256 ' + digest)


if __name__ == '__main__':
    main()
