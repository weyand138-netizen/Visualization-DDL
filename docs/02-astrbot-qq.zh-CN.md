# DDL + AstrBot／QQ 部署指南

[English](02-astrbot-qq.en.md)

## 1. 在 Ubuntu 从空数据部署 DDL

准备受支持的 Ubuntu、Git、Python 3.10+ 和 [Docker Engine 与 Compose](https://docs.docker.com/engine/install/ubuntu/)。把自己的域名解析到服务器，开放 TCP 80/443。示例域名不可用；不要把 8080、规划桥或 Docker 服务直接暴露到公网。

```bash
sudo git clone https://github.com/weyand138-netizen/Visualization-DDL.git /opt/ddl-dashboard
cd /opt/ddl-dashboard
sudo cp .env.example .env
sudo chmod 600 .env
sudoedit .env
```

将 `DDL_DOMAIN` 改为自己的域名，`DDL_PASSWORD` 设为新密码，登录名是 `admin`。单账户时留空 `DDL_USERS_JSON`。首次启动会创建空的命名数据卷，不含任何已有日程；安装脚本会复用已有数据卷，不会重置数据。

增加独立账户时，在本机交互生成密码哈希：

```bash
python3 -c 'import getpass,server; print(server.password_hash(getpass.getpass("New account password: ")))'
```

在私有 `.env` 中填写 `DDL_USERS_JSON={"alice":{"passwordHash":"YOUR_GENERATED_HASH","displayName":"Alice"}}`。账户名必须匹配 `[a-z][a-z0-9_-]{0,31}`，`admin` 保留。不要提交配置或哈希。提供的插件安装器读取普通 `KEY=value`；若值包含 `$`，使用 Compose 的单引号字面量语法，并通过 AstrBot 设置界面配置插件，不使用 Python 安装器读取该文件。

## 2. 按原文安装 AstrBot 与 NapCat

直接参考 [AstrBot 官方 Docker 部署](https://docs.astrbot.app/deploy/astrbot/docker.html)、[OneBot 接入](https://docs.astrbot.app/platform/aiocqhttp.html)和 [NapCat 官方文档](https://napneko.github.io/guide/napcat)，完成 QQ 登录及反向 WebSocket。它们是独立前置软件，本仓库不打包它们。

先在 AstrBot 中配置能正常使用的模型，再把其已有提供商 ID 选给 DDL 插件；图片输入要求模型支持识图。安装脚本不会覆盖模型密钥或平台配置。NapCat、AstrBot 和 DDL 机器人接口应在私有网络中互通。示例端口为 OneBot 反向 WebSocket 6199、DDL 规划桥 6198，以自己的设置为准。

## 3. 安装与连接插件

通过 `docker network ls` 查看 AstrBot 已有的网络，将 `.env` 的 `ASTRBOT_NETWORK` 设为该网络名称。运行 `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成内部令牌，填入 `DDL_BOT_TOKEN`；设置 `DDL_AI_URL=http://astrbot:6198`，其中主机名替换为实际内部服务名。DDL 在该网络的别名为 `ddl-dashboard`。

```bash
sudo bash deploy/install-ubuntu.sh /opt/ddl-dashboard/.env astrbot
sudo python3 deploy/install_astrbot.py \
  --data-dir /opt/astrbot/data \
  --env-file /opt/ddl-dashboard/.env \
  --provider-id YOUR_EXISTING_PROVIDER_ID
```

把 AstrBot 路径改为实际宿主机数据挂载目录。也可手动把 `integrations/astrbot_plugin_ddl` 复制到 AstrBot 插件目录，再通过界面设置。重载插件后，工作台地址为 `http://ddl-dashboard:8080`，桥端口为 6198，`bot_token` 与 DDL 的令牌一致。通过私有 Docker 网络让 DDL 能访问桥，不需要映射桥端口到公网。

脚本会在 AstrBot 数据目录备份原插件和配置，保留已有模型、平台和 QQ 设置；令牌冲突时停止。备份属于私有运行数据。首次安装默认关闭 QQ 读写：在插件中填写允许的 QQ 号以及 `QQ_ID:account` 绑定，每个 QQ 只能唯一绑定到一个已有 DDL 登录账户。白名单和绑定必须同时通过，未绑定或重复绑定都会拒绝。

## 4. 验收自己的演示日程

1. 打开 `https://YOUR_HOSTNAME` 登录，先确认日程为空，再手动添加测试事项，并检查其他账户不可见。
2. 用授权 QQ 私聊发送 `/日程 查看本周日程`，再发送 `/日程 2030年4月15日14点添加“演示交付”，收入1200元`。
3. 在网页确认内容，明确要求完成、到账，然后明确删除该测试事项。使用未授权身份检查拒绝且没有写入。
4. 用虚构图片测试识图模型，核对日期与金额。网页 AI 预览可以先检查计划再提交。

这些是部署者需要执行的验收步骤，不代表本次发布主动操作了真实 QQ。实际验证证据见 [VALIDATION.md](VALIDATION.md)。

## 5. 备份、升级与恢复

运行 `sudo python3 deploy/backup_ubuntu.py` 对所有账户执行 SQLite 一致性备份，每账户保留十四份。默认容器为 `visualization-ddl-ddl-1`，目录为 `/var/backups/ddl-dashboard`，可通过 `DDL_CONTAINER`、`DDL_BACKUP_DIR` 覆盖。另行安全保存 `.env` 和 AstrBot 配置。可选定时器 `deploy/ddl-backup.*` 默认源码位于 `/opt/ddl-dashboard`，启用前核对路径。

升级前备份，执行 `sudo git pull --ff-only` 后重新运行相同安装命令，插件变更时重新安装并重载。升级保留数据卷，**不要运行 `down -v`**。恢复时先停止 DDL，将一致性备份还原到数据卷中对应账户的数据库路径，只在停机时清除该数据库陈旧的 WAL/SHM 文件后启动；先在独立临时数据卷演练恢复。

HTTPS 故障检查 DNS、80/443 与 Caddy 日志；AI 入口隐藏时检查 DDL 容器是否收到两个 AI 配置变量并重启；QQ 拒绝时检查私聊、前缀、白名单与唯一绑定；规划失败检查模型 ID、识图能力、令牌与内网连通。日志可能包含输入内容，不要直接公开上传。
