# DDL MCP connector

Optional Python 3.11+ local stdio server for AIRI desktop and other MCP hosts. Uses the official `mcp==2.3.0` SDK. It authenticates as one DDL web account and has no dependency on AstrBot or NapCat.

```bash
python -m pip install ./integrations/ddl_mcp
```

Set `DDL_BASE_URL`, `DDL_USERNAME`, `DDL_PASSWORD` in the MCP host's local environment configuration and launch `ddl-mcp` (or `python -m ddl_mcp.server`). Remote URLs require HTTPS; HTTP is accepted only for loopback. Redirects are refused. Do not commit your real host configuration.

Tools: `ddl_list_events`, `ddl_create_event`, `ddl_update_event`, `ddl_delete_event`. Query results include `version`, `beijingNow`, `timezone`, pagination and event data. Edits require `expected_version`. `incomeCents` is integer RMB cents; `time=""` means all day. List dates are inclusive. A write retry uses the same request ID; an unresolved network failure requires querying before another write.

Only events and necessary operational context reach the model. No chat history is persisted by the connector. Tool usage rules guide model behavior; they are not a guarantee of semantic accuracy.

See the complete [English](../../docs/03-airi.en.md) / [中文](../../docs/03-airi.zh-CN.md) guide and root MIT license.
