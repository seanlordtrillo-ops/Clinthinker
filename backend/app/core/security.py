"""Blocks requests that don't come from this computer's own app.

The backend only listens on this computer, but a web page open in any browser on the
same computer could still try to send it requests. This guard stops two such attacks:

- DNS rebinding: a site whose name points at 127.0.0.1 reaches the backend with its
  own name in the Host header. Only local host names are accepted.
- Cross-site requests (CSRF): another site submits a form or upload to the backend.
  Requests that change data must come from the app's own local page.
"""
from __future__ import annotations

import json
from urllib.parse import urlsplit

ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "testserver"})
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def host_name(value: str) -> str:
    """'localhost:5173' -> 'localhost', '[::1]:8000' -> '::1'."""
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def is_local_origin(origin: str) -> bool:
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return parts.scheme in {"http", "https"} and (parts.hostname or "") in ALLOWED_HOSTS


def rejection(method: str, path: str, headers: dict[str, str]) -> tuple[int, str] | None:
    """Return (status, message) when a request must be refused, otherwise None."""
    host = host_name(headers.get("host", ""))
    if host and host not in ALLOWED_HOSTS:
        return 400, "This request came from an unknown address and was blocked."
    if method in UNSAFE_METHODS and path.startswith("/api/"):
        origin = headers.get("origin")
        if headers.get("sec-fetch-site") == "cross-site" or (origin and not is_local_origin(origin)):
            return 403, "Requests from other websites are not allowed."
    return None


class LocalRequestGuard:
    """ASGI middleware that applies `rejection` to every HTTP request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            refused = rejection(scope.get("method", "GET"), scope.get("path", ""), headers)
            if refused:
                status, message = refused
                body = json.dumps({"detail": message}).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": status,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                })
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
