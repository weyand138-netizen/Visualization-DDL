"""The installer may only change its own plugin and private plugin config."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_existing_provider_platform_and_bindings_survive_reinstall(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = base / 'config/astrbot_plugin_ddl_config.json'
            config.parent.mkdir()
            original = {'provider_id': 'fixture-existing-provider', 'bot_token': '',
                        'allowed_qq': ['1000000001'], 'qq_accounts': ['1000000001:alice'],
                        'dashboard_url': 'http://fixture-internal:8080', 'bridge_port': 6198}
            config.write_text(json.dumps(original), encoding='utf-8')
            platform = base / 'platform-fixture.json'
            platform.write_text('{"fixture":"unchanged"}', encoding='utf-8')
            environment = base / 'fixture.env'
            environment.write_text('DDL_BOT_TOKEN=fixture-internal-token\n', encoding='utf-8')
            subprocess.run([sys.executable, str(ROOT / 'deploy/install_astrbot.py'), '--data-dir', str(base),
                            '--env-file', str(environment), '--provider-id', 'fixture-new-provider'],
                           check=True, capture_output=True)
            installed = json.loads(config.read_text())
            self.assertEqual(installed, {**original, 'bot_token': 'fixture-internal-token'})
            self.assertEqual(platform.read_text(), '{"fixture":"unchanged"}')
            self.assertTrue((base / 'plugins/astrbot_plugin_ddl/main.py').is_file())
            self.assertEqual(len(list((base / 'ddl-plugin-backups').glob('*/config.json'))), 1)

    def test_token_conflict_aborts_without_overwriting_config(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            config = base / 'config/astrbot_plugin_ddl_config.json'
            config.parent.mkdir()
            config.write_text('{"provider_id":"fixture-provider","bot_token":"fixture-old-token"}')
            original = config.read_bytes()
            environment = base / 'fixture.env'
            environment.write_text('DDL_BOT_TOKEN=fixture-other-token\n')
            result = subprocess.run([sys.executable, str(ROOT / 'deploy/install_astrbot.py'), '--data-dir', str(base),
                                     '--env-file', str(environment)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(config.read_bytes(), original)
            self.assertFalse((base / 'plugins').exists())


if __name__ == '__main__':
    unittest.main()
