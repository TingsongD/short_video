"""Local security (F27): loopback-only semantics, Host/Origin
validation, local session + CSRF for mutations.
"""
import json as _json
import secrets

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver"}


def host_ok(host):
    return (host or "").split(":")[0].lower() in LOCAL_HOSTS


class LocalSecurityMiddleware:
    """Pure ASGI middleware: Host check for all, Origin + CSRF for
    mutations. Session token is issued by POST /api/session."""

    def __init__(self, app, session_token):
        self.app = app
        self.token = session_token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode(): v.decode()
                   for k, v in scope.get("headers", [])}
        method = scope.get("method", "GET")
        path = scope.get("path", "")

        if not host_ok(headers.get("host", "")):
            return await _deny(send, 403, "bad_host",
                             "loopback hosts only")
        if method in SAFE_METHODS or path == "/api/session":
            return await self.app(scope, receive, send)

        origin = headers.get("origin")
        if origin:
            ohost = origin.split("://", 1)[-1].split("/")[0]
            if not host_ok(ohost):
                return await _deny(send, 403, "bad_origin",
                                   "mutation origin not allowed")
        if headers.get("x-csrf-token") != self.token:
            return await _deny(send, 403, "csrf",
                               "missing or invalid CSRF token")
        return await self.app(scope, receive, send)


async def _deny(send, status, code, detail):
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body",
                "body": _json.dumps({"error": code,
                                     "detail": detail}).encode()})


def new_session_token():
    return secrets.token_urlsafe(24)
