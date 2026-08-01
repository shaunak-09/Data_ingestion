"""Mock student API: OAuth2 client-credentials token endpoint plus a paginated `/students`.

Standard library only. Two ways to use it:

    with mock_api(MockApiState(students=[...])) as (base_url, state):   # tests
    python -m tests.mock_api.server                                    # local runs, port 8099

It can be told to fail on purpose (429 once, 500 always, reject a token) so retry, rate-limit
and token-refresh paths are exercised over real HTTP.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

DEFAULT_CLIENT_ID = "local-client"
DEFAULT_CLIENT_SECRET = "local-secret"
DEFAULT_PORT = 8099

TOKEN_PATH = "/oauth2/token"
STUDENTS_PATH = "/students"


@dataclass
class MockApiState:
    """Data plus the failure switches a test wants to flip."""

    students: list[dict[str, Any]]
    page_size: int = 2
    token_lifetime_seconds: int = 3600
    client_id: str = DEFAULT_CLIENT_ID
    client_secret: str = DEFAULT_CLIENT_SECRET
    retry_after_seconds: int = 1
    use_next_url: bool = False
    rate_limit_pages_once: set[int] = field(default_factory=set)
    server_error_pages: set[int] = field(default_factory=set)
    rejected_tokens: set[str] = field(default_factory=set)
    issued_tokens: list[str] = field(default_factory=list)
    page_requests: list[int] = field(default_factory=list)
    updated_since_seen: list[str | None] = field(default_factory=list)

    def issue_token(self) -> str:
        token = f"mock-token-{len(self.issued_tokens) + 1}"
        self.issued_tokens.append(token)
        return token

    def reject_current_token(self) -> None:
        """Simulate the newest token expiring server-side."""
        if self.issued_tokens:
            self.rejected_tokens.add(self.issued_tokens[-1])


def _parse_timestamp(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class _Handler(BaseHTTPRequestHandler):
    state: MockApiState

    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # keep test output clean
        return

    def _send_json(
        self, status: int, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming
        if urlparse(self.path).path != TOKEN_PATH:
            self._send_json(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        client_id = (form.get("client_id") or [""])[0]
        client_secret = (form.get("client_secret") or [""])[0]
        if client_id != self.state.client_id or client_secret != self.state.client_secret:
            self._send_json(401, {"error": "invalid_client"})
            return
        self._send_json(
            200,
            {
                "access_token": self.state.issue_token(),
                "token_type": "Bearer",
                "expires_in": self.state.token_lifetime_seconds,
            },
        )

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        if parsed.path != STUDENTS_PATH:
            self._send_json(404, {"error": "not_found"})
            return

        header = self.headers.get("Authorization", "")
        token = header.removeprefix("Bearer ").strip()
        if token not in self.state.issued_tokens or token in self.state.rejected_tokens:
            self._send_json(401, {"error": "invalid_token"})
            return

        query = parse_qs(parsed.query)
        page = int((query.get("page") or ["1"])[0])
        page_size = int((query.get("page_size") or [str(self.state.page_size)])[0])
        updated_since = (query.get("updated_since") or [None])[0]
        self.state.page_requests.append(page)
        self.state.updated_since_seen.append(updated_since)

        if page in self.state.server_error_pages:
            self._send_json(500, {"error": "server_error"})
            return
        if page in self.state.rate_limit_pages_once:
            self.state.rate_limit_pages_once.discard(page)
            self._send_json(
                429,
                {"error": "rate_limited"},
                {"Retry-After": str(self.state.retry_after_seconds)},
            )
            return

        records = self.state.students
        if updated_since:
            cutoff = _parse_timestamp(updated_since)
            records = [
                record for record in records if _parse_timestamp(str(record["updated_at"])) > cutoff
            ]

        total_pages = max(1, -(-len(records) // page_size))
        start = (page - 1) * page_size
        has_next = page < total_pages
        body: dict[str, Any] = {
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "data": records[start : start + page_size],
        }
        if self.state.use_next_url:
            # The other common vendor style: a ready-made link instead of a page number.
            since = f"&updated_since={updated_since}" if updated_since else ""
            link = f"{STUDENTS_PATH}?page={page + 1}&page_size={page_size}{since}"
            body["next"] = link if has_next else None
        else:
            body["next_page"] = page + 1 if has_next else None
        self._send_json(200, body)


@contextmanager
def mock_api(state: MockApiState, port: int = 0) -> Iterator[tuple[str, MockApiState]]:
    """Serve `state` on a background thread. Yields (base_url, state)."""
    handler = type("BoundHandler", (_Handler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def sample_students() -> list[dict[str, Any]]:
    """Records from samples/api_page*.json, so local runs use the committed payloads."""
    samples = Path(__file__).resolve().parents[2] / "samples"
    records: list[dict[str, Any]] = []
    for name in ("api_page1.json", "api_page2.json"):
        payload = json.loads((samples / name).read_text(encoding="utf-8"))
        records.extend(payload["data"])
    return records


def main() -> None:
    state = MockApiState(students=sample_students(), page_size=2)
    with mock_api(state, port=DEFAULT_PORT) as (base_url, _):
        print(f"mock student API on {base_url}")
        print(f"  token:    POST {base_url}{TOKEN_PATH}")
        print(f"  students: GET  {base_url}{STUDENTS_PATH}?page=1&page_size=2")
        print(f"  client_id={DEFAULT_CLIENT_ID} client_secret={DEFAULT_CLIENT_SECRET}")
        print("Ctrl+C to stop")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            print("stopping")


if __name__ == "__main__":
    main()
