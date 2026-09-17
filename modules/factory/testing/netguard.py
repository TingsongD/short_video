"""Outbound-network guard for offline QA runs.

Blocks plain sockets while permitting explicitly selected loopback services
and local render binaries. Used by harness runs and pytest to prove cases
make no unexpected external calls.
"""
import socket


class BlockedNetworkCall(RuntimeError):
    pass


class NetworkGuard:
    """Monkeysocket patcher: deny all outbound except allowlisted hosts."""

    def __init__(self, allow=()):
        self.allow = {"127.0.0.1", "localhost", "::1", *allow}
        self.attempts = []
        self._orig = None

    def _blocked_connect(self, host):
        self.attempts.append(host)
        if host not in self.allow:
            raise BlockedNetworkCall(
                f"outbound connection to {host!r} is not allowed in this mode")

    def __enter__(self):
        guard = self
        self._orig = socket.socket
        self._orig_gai = socket.getaddrinfo

        class GuardedSocket(socket.socket):
            def connect(self, address):
                host = address[0] if isinstance(address, tuple) else str(address)
                guard._blocked_connect(host)
                return super().connect(address)

            def connect_ex(self, address):
                host = address[0] if isinstance(address, tuple) else str(address)
                guard._blocked_connect(host)
                return super().connect_ex(address)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self.close()
                return False

        def guarded_getaddrinfo(host, *a, **kw):
            if host is None:
                return self._orig_gai(host, *a, **kw)
            if host not in self.allow:
                self.attempts.append(host)
                raise BlockedNetworkCall(
                    f"DNS/connect to {host!r} is not allowed in this mode")
            return self._orig_gai(host, *a, **kw)

        socket.socket = GuardedSocket
        socket.getaddrinfo = guarded_getaddrinfo
        return self

    def __exit__(self, *exc):
        socket.socket = self._orig
        socket.getaddrinfo = self._orig_gai
        return False
