"""Account-bound HTTP access; never sends the bot token or follows redirects."""

import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
import uuid
from http.client import IncompleteRead
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from mcp.server.mcpserver.exceptions import ToolError


class DDLConnectionError(ToolError):
    """A safe error suitable for returning to a model without credentials."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DDLConnectionError("DDL redirects are refused. Configure the final HTTPS URL.")


@dataclass(frozen=True)
class Config:
    base_url: str
    username: str
    password: str = field(repr=False)

    def __post_init__(self):
        value = urlsplit(self.base_url)
        try:
            loopback = ipaddress.ip_address(value.hostname or "").is_loopback
        except ValueError:
            loopback = value.hostname == "localhost"
        if (not value.hostname or value.username is not None or value.password is not None
                or value.query or value.fragment or value.scheme not in ("http", "https")
                or (value.scheme == "http" and not loopback)):
            raise ValueError("DDL_BASE_URL must be HTTPS, or HTTP on a loopback address, without URL credentials/query/fragment.")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", self.username) or not self.password:
            raise ValueError("Set DDL_USERNAME to a valid account and DDL_PASSWORD to its password.")

    @classmethod
    def from_environment(cls):
        return cls(*(os.environ.get(key, "") for key in ("DDL_BASE_URL", "DDL_USERNAME", "DDL_PASSWORD")))


def snapshot_version(event):
    """Hash the complete server snapshot, including its id and creation time."""
    return hashlib.sha256(json.dumps(event, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


class DDLClient:
    """Bind all reads and writes to one configured login account."""

    def __init__(self, config, timeout=3):
        self.config = config
        self.timeout = timeout
        self.opener = build_opener(NoRedirect())

    def request(self, path, payload=None):
        raw = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        authorization = base64.b64encode(f"{self.config.username}:{self.config.password}".encode()).decode()
        # Calendar retries reuse the body/requestId and bot_requests result.
        # Focus controls carry versions; an uncertain reply requires a fresh read.
        query_target = "the current focus timer" if path.startswith("/api/focus") else "events"
        for attempt in range(2 if payload is not None else 1):
            req = Request(self.config.base_url.rstrip("/") + path, data=raw,
                          headers={"Authorization": "Basic " + authorization,
                                   "X-DDL-Account": self.config.username,
                                   "Content-Type": "application/json"})
            try:
                with self.opener.open(req, timeout=self.timeout) as response:
                    body = response.read(16 * 1024 * 1024 + 1)
                    if len(body) > 16 * 1024 * 1024:
                        raise DDLConnectionError("DDL response is too large; archive old events.")
                    return json.loads(body)
            except HTTPError as error:
                # Do not reflect arbitrary server bodies or credentials to the model.
                messages = {401: "DDL login failed.", 403: "DDL access denied.",
                            409: "DDL account changed. Reconnect with the configured account.",
                            400: f"DDL rejected invalid or stale data. Query {query_target} again before editing."}
                if payload is not None and error.code >= 500:
                    raise DDLConnectionError(f"Write result is uncertain. Query {query_target} before another write.") from None
                raise DDLConnectionError(messages.get(error.code, f"DDL HTTP error {error.code}.")) from None
            except (URLError, TimeoutError, socket.timeout, ConnectionError, OSError, IncompleteRead):
                if payload is not None and attempt == 0:
                    continue
                message = (f"Write result is uncertain. Query {query_target} before another write; do not blindly recreate it."
                           if payload is not None else "DDL cannot be reached. Check its address and connection.")
                raise DDLConnectionError(message) from None
            except (ValueError, UnicodeError):
                message = (f"Write result is uncertain: invalid response. Query {query_target} before another write."
                           if payload is not None else "DDL returned invalid JSON.")
                raise DDLConnectionError(message) from None

    def events(self):
        state = self.request("/api/state")
        if (not isinstance(state, dict) or not isinstance(state.get("account"), dict)
                or state["account"].get("id") != self.config.username
                or not isinstance(state.get("events"), list)):
            raise DDLConnectionError("DDL returned an unexpected account or event list.")
        # Calendar queries do not expose preferences or focus data.
        return state["events"]

    def focus_timer(self, command=None, open_widget=False):
        """Read/control DDL's shared timer; optionally grant focus-only widget access."""
        result = self.request("/api/focus-timer", command)
        if not isinstance(result, dict) or result.get("account") != self.config.username or not isinstance(result.get("timer"), dict):
            raise DDLConnectionError("DDL returned an unexpected focus timer account.")
        if open_widget:
            grant = self.request("/api/focus-widget-token", {})
            token = grant.get("token") if isinstance(grant, dict) else None
            if not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{20,128}", token):
                raise DDLConnectionError("DDL returned an invalid focus widget capability.")
            result["widget"] = {"url": self.config.base_url.rstrip("/") + "/focus-widget#token=" + token}
        return result

    def current(self, event_id, expected_version):
        event = next((item for item in self.events() if item.get("id") == event_id), None)
        if not event or snapshot_version(event) != expected_version:
            raise DDLConnectionError("Event is missing or has changed. Query again and use the new version.")
        return event

    def open_calendar(self, selected_date):
        """Issue read-only access to DDL's own calendar UI for one account."""
        grant = self.request("/api/calendar-widget-token", {})
        if not isinstance(grant, dict) or grant.get("account") != self.config.username:
            raise DDLConnectionError("DDL returned an unexpected calendar account.")
        token = grant.get("token")
        if not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{20,128}", token):
            raise DDLConnectionError("DDL returned an invalid calendar widget capability.")
        return {"account": self.config.username, "widget": {
            "url": self.config.base_url.rstrip("/") + "/calendar-widget?date=" + selected_date + "#token=" + token}}

    def apply(self, action):
        request_id = "mcp-" + uuid.uuid4().hex
        result = self.request("/api/events/batch", {"requestId": request_id, "actions": [action]})
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            raise DDLConnectionError("Unexpected write response. Query events to confirm the result.")
        return {"requestId": request_id, "results": result["results"]}
