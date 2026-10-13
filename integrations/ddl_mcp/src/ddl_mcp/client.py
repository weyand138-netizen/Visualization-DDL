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
        # A write retry reuses exactly the same body and requestId. SQLite's
        # bot_requests table returns the original result after a lost response.
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
                            400: "DDL rejected invalid or stale data. Query events again before editing."}
                if payload is not None and error.code >= 500:
                    raise DDLConnectionError("Write result is uncertain. Query events before another write.") from None
                raise DDLConnectionError(messages.get(error.code, f"DDL HTTP error {error.code}.")) from None
            except (URLError, TimeoutError, socket.timeout, ConnectionError, OSError, IncompleteRead):
                if payload is not None and attempt == 0:
                    continue
                message = ("Write result is uncertain. Query events before another write; do not blindly recreate it."
                           if payload is not None else "DDL cannot be reached. Check its address and connection.")
                raise DDLConnectionError(message) from None
            except (ValueError, UnicodeError):
                message = ("Write result is uncertain: invalid response. Query events before another write."
                           if payload is not None else "DDL returned invalid JSON.")
                raise DDLConnectionError(message) from None

    def events(self):
        state = self.request("/api/state")
        if (not isinstance(state, dict) or not isinstance(state.get("account"), dict)
                or state["account"].get("id") != self.config.username
                or not isinstance(state.get("events"), list)):
            raise DDLConnectionError("DDL returned an unexpected account or event list.")
        # preferences/focus/capabilities are deliberately not exposed through MCP.
        return state["events"]

    def current(self, event_id, expected_version):
        event = next((item for item in self.events() if item.get("id") == event_id), None)
        if not event or snapshot_version(event) != expected_version:
            raise DDLConnectionError("Event is missing or has changed. Query again and use the new version.")
        return event

    def apply(self, action):
        request_id = "mcp-" + uuid.uuid4().hex
        result = self.request("/api/events/batch", {"requestId": request_id, "actions": [action]})
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            raise DDLConnectionError("Unexpected write response. Query events to confirm the result.")
        return {"requestId": request_id, "results": result["results"]}
