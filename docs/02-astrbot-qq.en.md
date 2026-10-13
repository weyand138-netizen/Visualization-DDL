# DDL with AstrBot / QQ

[中文](02-astrbot-qq.zh-CN.md)

## 1. Deploy an empty DDL on Ubuntu

Use a supported Ubuntu installation with Git, Python 3.10+ and [Docker Engine with Compose](https://docs.docker.com/engine/install/ubuntu/). Point your own domain at the server and allow inbound TCP 80/443. The example domain is not a real endpoint. Do not expose 8080, the bot bridge or your Docker daemon publicly.

```bash
sudo git clone https://github.com/weyand138-netizen/Visualization-DDL.git /opt/ddl-dashboard
cd /opt/ddl-dashboard
sudo cp .env.example .env
sudo chmod 600 .env
sudoedit .env
```

Set `DDL_DOMAIN` to your hostname and `DDL_PASSWORD` to a new strong password (login username `admin`). Leave `DDL_USERS_JSON` empty for one account. The example file contains no calendar or credentials. Compose creates an empty named data volume on first start; no imported data is necessary. Existing volumes are reused, never reset by the installer.

To add an isolated account, generate its hash locally with an interactive prompt:

```bash
python3 -c 'import getpass,server; print(server.password_hash(getpass.getpass("New account password: ")))'
```

Put the generated value in `.env` as `DDL_USERS_JSON={"alice":{"passwordHash":"YOUR_GENERATED_HASH","displayName":"Alice"}}`. Use lower-case account IDs matching `[a-z][a-z0-9_-]{0,31}`; `admin` is reserved. Do not commit this file or the generated hash. Use bare `KEY=value` entries with the supplied installer; for Compose values containing `$`, use Compose's literal single-quote syntax and install the plugin through its settings UI instead of the Python installer.

## 2. Install AstrBot and NapCat using their documentation

Follow [AstrBot Docker installation](https://docs.astrbot.app/deploy/astrbot/docker.html), [AstrBot OneBot connection](https://docs.astrbot.app/platform/aiocqhttp.html) and [NapCat official guide](https://napneko.github.io/guide/napcat). Configure the QQ login and reverse WebSocket in those applications. They are separate prerequisites, not bundled in this repository.

Configure a working model provider in AstrBot. Select its existing provider ID for this plugin; image instructions require a provider supporting images. The installer does not replace provider credentials, models or platform settings. Keep NapCat, AstrBot and the DDL bot API on an appropriate private Docker network. Example internal ports are OneBot reverse WebSocket 6199 and the DDL planning bridge 6198; use your configured values.

## 3. Connect the plugin

Determine the Docker network already used by AstrBot (`docker network ls`). Set `ASTRBOT_NETWORK` to its name. Generate an internal token with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` and put it in private `.env` as `DDL_BOT_TOKEN`. Set `DDL_AI_URL=http://astrbot:6198` using AstrBot's actual internal service name. The included DDL network alias is `ddl-dashboard`.

```bash
sudo bash deploy/install-ubuntu.sh /opt/ddl-dashboard/.env astrbot
sudo python3 deploy/install_astrbot.py \
  --data-dir /opt/astrbot/data \
  --env-file /opt/ddl-dashboard/.env \
  --provider-id YOUR_EXISTING_PROVIDER_ID
```

Replace the AstrBot host data path with your actual mounted data directory. Alternatively copy `integrations/astrbot_plugin_ddl` into AstrBot's plugin directory and enter the configuration through AstrBot. Reload the plugin. Its dashboard address is `http://ddl-dashboard:8080`, its bridge port is 6198, and its `bot_token` must match `DDL_BOT_TOKEN`. Make the bridge reachable from the DDL container using private networking. No public port mapping is needed for it.

The installer backs up the previous plugin/config under your AstrBot data directory, keeps existing provider, platform and QQ settings, and aborts on a token mismatch. Backups are private operational data. On first install **QQ access is disabled**: enter allowed QQ IDs and explicit `QQ_ID:account` bindings in the plugin settings. Each QQ ID must have exactly one binding to an existing DDL login. The allowlist and binding must both pass. An unbound or duplicate mapping is rejected.

Legacy behavior: when the entire binding list is empty, allowlisted QQ identities use `admin` for compatibility with older single-account configurations. For explicit account isolation, keep a nonempty binding list and map every authorized identity; the unbound/duplicate rejection above applies when bindings are configured.

## 4. Validate with your own test calendar

1. Open `https://YOUR_HOSTNAME`, sign in and confirm the calendar is empty before adding a clearly named test event. Confirm another account cannot see it.
2. In an authorized QQ private chat send `/日程 查看本周日程`, then `/日程 2030年4月15日14点添加“演示交付”，收入1200元`.
3. Confirm the exact event on the dashboard. Ask to mark that event completed and paid; then explicitly delete it. Test an unauthorized QQ identity and verify rejection without a write.
4. Try a harmless demonstration image with an image-capable provider. Check the proposed dates and amounts. Web AI previews allow reviewing the plan before applying it.

These are deployment acceptance steps for the operator, not a claim that this release sent messages from your QQ account. See [validation evidence](VALIDATION.md).

## 5. Backup, upgrade and recovery

Run `sudo python3 deploy/backup_ubuntu.py` for a SQLite-consistent backup of every account; it retains fourteen per account. Defaults are container `visualization-ddl-ddl-1` and `/var/backups/ddl-dashboard`; override with `DDL_CONTAINER` and `DDL_BACKUP_DIR` if needed. Store `.env` and AstrBot configuration separately and securely. Optional timer units in `deploy/ddl-backup.*` assume checkout `/opt/ddl-dashboard`; review paths before enabling them.

Before upgrading, back up, then `sudo git pull --ff-only` and rerun the same installer. Reinstall/reload the plugin if changed. Keep the volume; **do not run `down -v`** to upgrade. For recovery, stop DDL, restore each consistent backup to its account's database path inside the data volume, remove only stale WAL/SHM siblings while stopped, and restart. Test a recovery on a separate disposable volume before relying on it.

If HTTPS fails, check DNS, 80/443 and Caddy logs. If AI is hidden, verify DDL received both `DDL_AI_URL` and `DDL_BOT_TOKEN`, then restart it. If QQ is rejected, check private chat, prefix, allowlist and unique binding. If planning fails, check the provider ID, image capability, matching tokens and internal connectivity. Logs may contain private inputs; never upload them without redaction.
