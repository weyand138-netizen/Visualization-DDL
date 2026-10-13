# Validation / 验证记录

Release candidate: **1.1.0**, prepared 2026-10-13. Tests use disposable SQLite databases, fictional accounts and new sessions. This document deliberately separates protocol/fixture checks from real desktop/model and real QQ delivery checks.

| Component / 组件 | Environment / 环境 | Result / 结果 |
|---|---|---|
| Dashboard JavaScript | Windows, Node 24.11.1 | 19 tests passed: calendar/income/focus/account-local storage |
| DDL HTTP/SQLite, AstrBot adapter and installer | Windows, Python 3.12.14 | 27 tests passed: accounts, event batches, focus, permissions, image parsing and configuration preservation |
| MCP connector | Windows, Python 3.12.14, official mcp 2.3.0 | 6 tests passed, including actual stdio subprocess client discovery and CRUD |
| MCP error/security cases | Same disposable fixture | Bad credentials, account mismatch/isolation, invalid date, stale version, redirect credential protection, duplicate request after lost reply and repeated timeout passed |
| Dashboard browser | Headless Microsoft Edge, 1440px viewport | No JavaScript errors; unconfigured AI entry hidden; new synthetic light/dark screenshots |
| Ubuntu Compose definitions | Docker Compose config validation | Standalone and AstrBot overlay parse with fictional environment values |
| Ubuntu/Windows CI | Python 3.11 and 3.12, Node 22 | All four jobs passed in [run 38339776423](https://github.com/weyand138-netizen/Visualization-DDL/actions/runs/38339776423) |
| Standalone container | Ubuntu CI | Passed in the same run: built source-only image, empty events and disabled AI with no AstrBot/NapCat |
| Source release archive | Extracted into a new temporary directory | 27 backend/plugin/installer tests passed; no data directory, credentials or Git metadata |
| Official AIRI desktop | Upstream main MCP source inspected 2026-10-13 | stdio configuration/protocol compatible by inspection; **desktop natural-language run not completed** |
| airi-HA desktop | 0.10.2, source commit e1b83e31f46ebd3a30a1b1b20998379b3508cda7 | Same stdio client/config verified by inspection; **desktop natural-language run not completed** |
| Existing Ubuntu deployment | Prior running DDL/AstrBot/NapCat setup | Service/account checks and actual text/image model planning exercised; no production writes for this release |
| Real QQ end-to-end | Real private chat message and response | **Not actively executed for this publication** |
| Public HTTPS clean install | New domain, certificate issuance, fresh Ubuntu machine | **Operator acceptance still required**; Compose parsing/container smoke does not prove DNS/certificate setup |

Local Docker Engine was unavailable, so local container startup could not be claimed. Neither an installed official AIRI desktop nor a built airi-HA desktop was available in the isolated test environment. No private AIRI model/profile configuration was copied or altered to simulate success. The first release is a **preview** pending those desktop acceptance runs and a fresh public HTTPS deployment. SDK interoperability is tested; universal desktop compatibility is not certified.

中文：本地已通过前端 19 项、后端／插件／安装器 27 项、MCP 6 项测试，使用真实 MCP 客户端与临时数据库；浏览器检查与 Compose 配置检查通过。公开 CI 的 Windows／Ubuntu、Python 3.11／3.12 四组测试及独立 Linux 容器检查全部通过，源码包解压后的 27 项测试通过。官方 AIRI 与 airi-HA 桌面自然语言、真实 QQ 收发、新 Ubuntu 域名 HTTPS 完整部署尚未完成，不将源码兼容性检查写成端到端成功。首版标记为预览版。

## Reproduce / 复现

```bash
python -m pip install ./integrations/ddl_mcp
python tools/run_checks.py
```

This runs Node tests, standard-library backend/plugin tests, real MCP client tests and the source/history privacy check. It requires a Git checkout with Git installed. Check [Actions](https://github.com/weyand138-netizen/Visualization-DDL/actions) for the cross-platform matrix. Screenshots can be reproduced with `tests/visual_qa_server.py --port 18763 --control YOUR_PRIVATE_CONTROL_FILE`, then `tools/capture_demo.cjs` with a separately installed Playwright/browser; it connects only to loopback.

Before promoting to stable: record actual official AIRI release/commit, airi-HA build commit, model/provider, fresh test-session ID (redacted), discovery/query/create/partial edit/complete/paid/delete outcomes and dashboard observations. Perform the clean deployment and QQ guide's acceptance checks. Publish only redacted outcomes and synthetic media.
