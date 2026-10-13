"""Install only this plugin; preserve existing provider/platform/QQ settings."""
import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True, help='Your AstrBot host data directory')
    parser.add_argument('--env-file', type=Path, required=True, help='Private DDL environment file')
    parser.add_argument('--provider-id', help='Required for first install; use an existing configured provider ID')
    parser.add_argument('--dashboard-url', default='http://ddl-dashboard:8080')
    args = parser.parse_args()
    env = dict(line.split('=', 1) for line in args.env_file.read_text(encoding='utf-8-sig').splitlines()
               if '=' in line and not line.lstrip().startswith('#'))
    token = env.get('DDL_BOT_TOKEN', '').strip()
    if not token:
        parser.error('Set DDL_BOT_TOKEN in the private environment file')
    config_file = args.data_dir / 'config/astrbot_plugin_ddl_config.json'
    config = json.loads(config_file.read_text(encoding='utf-8-sig')) if config_file.exists() else {}
    if not config.get('provider_id') and not args.provider_id:
        parser.error('Choose --provider-id from the existing AstrBot providers')
    if config.get('bot_token') and config['bot_token'] != token:
        parser.error('Existing plugin token differs; synchronize your private configuration before reinstalling')
    target = args.data_dir / 'plugins/astrbot_plugin_ddl'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    if target.exists() or config_file.exists():
        backup = args.data_dir / 'ddl-plugin-backups' / stamp
        backup.mkdir(parents=True, mode=0o700)
        if target.exists():
            shutil.copytree(target, backup / 'plugin')
        if config_file.exists():
            shutil.copy2(config_file, backup / 'config.json')
            (backup / 'config.json').chmod(0o600)
    source = Path(__file__).resolve().parents[1] / 'integrations/astrbot_plugin_ddl'
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if not config.get('provider_id'):
        config['provider_id'] = args.provider_id
    config.setdefault('allowed_qq', [])
    config.setdefault('qq_accounts', [])
    config.setdefault('bridge_port', 6198)
    config.setdefault('dashboard_url', args.dashboard_url)
    config['bot_token'] = token
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    config_file.chmod(0o600)
    print('DDL plugin installed; existing model/platform/QQ settings preserved. Reload the plugin in AstrBot.')


if __name__ == '__main__':
    main()
