# DDL MCP connector

Optional Python 3.11+ local stdio server for AIRI desktop and other MCP hosts. Uses the official `mcp==2.3.0` SDK. It authenticates as one DDL web account and has no dependency on AstrBot or NapCat.

```bash
python -m pip install ./integrations/ddl_mcp
```

Set `DDL_BASE_URL`, `DDL_USERNAME`, `DDL_PASSWORD` in the MCP host's local environment configuration and launch `ddl-mcp` (or `python -m ddl_mcp.server`). Remote URLs require HTTPS; HTTP is accepted only for loopback. Redirects are refused. Do not commit your real host configuration.

The account is supplied by each operator's private local configuration, not embedded in the connector. The model cannot choose another account through tool arguments. Change the configuration and restart the connector to switch accounts. `admin` in examples is the generic default login name, not a published personal credential.

Tools: `ddl_list_events`, `ddl_create_event`, `ddl_update_event`, `ddl_delete_event`. Query results include `version`, `beijingNow`, `timezone`, pagination and event data. Edits require `expected_version`. `incomeCents` is integer RMB cents; `time=""` means all day. List dates are inclusive. A write retry uses the same request ID; an unresolved network failure requires querying before another write.

Focus tools: `ddl_get_focus_timer`, `ddl_start_focus_timer`, `ddl_open_focus_timer`, `ddl_close_focus_timer`, `ddl_control_focus_timer`. Start accepts `duration_minutes` (1–240, default 25), an optional `title`, and `auto_start` (default true). Controls accept `pause`, `resume`, or `reset` plus the timer's current `expected_version`. Close pauses and preserves progress by default, then instructs the host to hide the matching DDL window. Use `pause_timer=false` only for an explicit request to hide the window while timing continues. Open restores the paused session; it does not restart it. Existing active work is preserved.

DDL owns the compact component in `public/focus-widget.*`, the shared state in `focus_timer.py`, and completed statistics in its account SQLite database. The dashboard and AIRI window operate on the same timer. The updated AIRI desktop host automatically opens the DDL widget returned by start/open; other MCP hosts can display the supplied URL using their own UI support. This is not an AIRI-local timer. The component omits slogans and header icons/text, with AIRI branding in the bottom-right corner.

Timer widget URLs carry a 12-hour capability in their fragment, scoped to the focus API. Account credentials and calendar access are not handed to the embedded page. Only calendar/focus data and necessary operational context reach the model. No chat history is persisted by the connector. Tool usage rules guide model behavior; they are not a guarantee of semantic accuracy.

See the complete [English](../../docs/03-airi.en.md) / [中文](../../docs/03-airi.zh-CN.md) guide and root MIT license.

## Calendar window

`ddl_open_calendar(date?: "YYYY-MM-DD")` opens DDL's read-only calendar and selects the requested day, defaulting to today in Asia/Shanghai. `ddl_close_calendar()` closes only the calendar. AIRI automatically hosts the returned URL, using an independent window alongside the timer; do not spawn a second widget with `stage_widgets`. Existing calendar CRUD tools remain the way to change events through conversation.

DDL owns `public/calendar-widget.*`, with shared appearance in `public/widget.*`. The Monday-first six-week calendar shows daily counts and a chronological agenda (all-day entries last). Click an entry for details. Visible windows refresh every five seconds; hidden windows stop polling. The calendar capability is separate from the timer capability, expires after twelve hours, and authorizes only bounded reads from `/api/calendar-widget`. It cannot read settings, focus data, or write events. Reopen through AIRI after expiration. Credentials are never included in the page URL.

Restart DDL, the MCP connector and AIRI after upgrading. Calendar and timer open in separate resizable windows, with theme synchronization and AIRI branding in the corner. No web login is required after the account connector is configured.
