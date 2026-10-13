"""Cross-platform verification entry point; requires Node and installed connector."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
for command in [
    ['node', '--test', *[str(p) for p in sorted((root / 'tests').glob('*.test.js'))]],
    [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-v'],
    [sys.executable, '-m', 'unittest', 'discover', '-s', 'integrations/ddl_mcp/tests', '-v'],
    [sys.executable, 'tools/privacy_check.py', '--history'],
]:
    subprocess.run(command, cwd=root, check=True)
