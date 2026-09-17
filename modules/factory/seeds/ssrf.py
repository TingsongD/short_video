"""Fetch-target safety (F09 checklist 5): automatic URL fetches are
restricted to https on public hosts. Private, loopback, link-local and
cloud-metadata addresses are refused, as is every unsafe redirect hop.
DNS resolution is injectable so tests stay offline."""
import ipaddress
import socket
from urllib.parse import urlsplit

from ..domain.errors import ContractError

MAX_REDIRECTS = 3
MAX_BYTES = 512 * 1024 * 1024   # source-media download ceiling


class SSRFError(ContractError):
    pass


def _blocked_ip(ip):
    a = ipaddress.ip_address(ip)
    return not a.is_global


def _default_resolve(host):
    return {r[4][0] for r in socket.getaddrinfo(host, 443)}


def assert_fetchable(url, resolver=None):
    """Validate one fetch target. resolver: host -> iterable of IP strs;
    defaults to real DNS (never used in tests)."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise SSRFError("unsafe_url", "url", "unparseable")
    if parsed.scheme != "https":
        raise SSRFError("unsafe_scheme", "url", parsed.scheme or "none")
    if parsed.username or parsed.password:
        raise SSRFError("unsafe_url", "url", "embedded credentials")
    if parsed.port not in (None, 443):
        raise SSRFError("unsafe_port", "url", str(parsed.port))
    host = parsed.hostname
    if not host:
        raise SSRFError("unsafe_url", "url", "no host")
    try:
        ips = {host} if ipaddress.ip_address(host) else None
    except ValueError:
        ips = None
    if ips is None:
        resolve = resolver or _default_resolve
        try:
            ips = set(resolve(host))
        except OSError as e:
            raise SSRFError("resolve_failed", "url", str(e))
    for ip in ips:
        if _blocked_ip(ip):
            raise SSRFError("private_address", "url",
                            f"{host} resolves to non-public {ip}")
    return parsed


def check_redirect(url, hops, resolver=None):
    """Each redirect target is re-validated; chains beyond MAX_REDIRECTS
    are refused."""
    if hops >= MAX_REDIRECTS:
        raise SSRFError("redirect_limit", "url", url)
    return assert_fetchable(url, resolver=resolver)
