"""Vertex OAuth boundary (F17): credentials come through an injected
`loader()` so the adapter never touches gcloud state directly and the
token never enters project state or logs.

loader() → dict, one of:
  {"kind": "oauth", "access_token": str, "expiry": iso|None,
   "identity": str, "project": str, "scopes": [..], "quota_ok": bool}
  {"kind": "api_key", ...}               → rejected for this route
  raises AuthError(reason)               → loader/refresh failure
"""
import datetime

from ..testing.fakes import ProviderError


class AuthError(Exception):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


def credential_failure_reason(error):
    """Only return allow-listed codes; OAuth exception text can contain secrets.

    Import lazily so a missing optional Google SDK can itself be diagnosed.
    This classification describes credentials, NOT whether a paid request ran.
    """
    if isinstance(error, ImportError):
        return "credential_dependency_missing"
    try:
        from google.auth.exceptions import (DefaultCredentialsError,
                                             RefreshError, TransportError)
    except ImportError:
        return "loader_failed"
    if isinstance(error, DefaultCredentialsError):
        return "no_credentials"
    if isinstance(error, TransportError):
        return "credential_transport_failed"
    if isinstance(error, RefreshError):
        # Inspect privately; never persist/return the provider payload or URL.
        text = str(error).lower()
        if any(marker in text for marker in
               ("reauth", "invalid_rapt", "invalid_grant")):
            return "reauth_required"
        return "credential_refresh_failed"
    return "loader_failed"


class VertexAuth:
    """Session state for the configured Cloud identity + project."""

    def __init__(self, loader, project, location="global",
                 required_scopes=("cloud-platform",), now=None):
        self._loader = loader
        self.project = project
        self.location = location
        self.required_scopes = set(required_scopes)
        self._now = now or (lambda: datetime.datetime.now(
            datetime.timezone.utc))
        self._cred = None

    def _load(self):
        try:
            self._cred = self._loader()
        except AuthError as e:
            self._cred = {"kind": "error", "reason": e.reason}
        except Exception as e:
            self._cred = {"kind": "error",
                          "reason": credential_failure_reason(e)}

    def refresh(self):
        """Re-run the loader (e.g. after user reauthentication)."""
        self._load()
        return self.status()

    def _expired(self, cred):
        exp = cred.get("expiry")
        if cred.get("expired"):
            return True
        if not exp:
            return False
        try:
            when = datetime.datetime.fromisoformat(
                exp.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return True
        return when <= self._now()

    def status(self):
        """Readiness only — never carries the token."""
        if self._cred is None:
            self._load()
        c = self._cred or {}
        base = {"project": self.project, "location": self.location,
                "identity": c.get("identity")}
        if c.get("kind") == "api_key":
            return {**base, "ready": False, "reason": "api_key_only"}
        if c.get("kind") == "error":
            return {**base, "ready": False,
                    "reason": c.get("reason", "loader_failed")}
        if c.get("kind") != "oauth" or not c.get("access_token"):
            return {**base, "ready": False, "reason": "no_credentials"}
        if self._expired(c):
            return {**base, "ready": False, "reason": "expired"}
        if c.get("project") and c["project"] != self.project:
            return {**base, "ready": False, "reason": "wrong_project"}
        have = set(c.get("scopes") or [])
        if self.required_scopes and not self.required_scopes <= have:
            return {**base, "ready": False,
                    "reason": "missing_permission"}
        if c.get("quota_ok") is False:
            return {**base, "ready": False, "reason": "quota_exceeded"}
        return {**base, "ready": True, "reason": "ok"}

    def bearer(self):
        """Token for a transport call; raises with the named reason."""
        self._load()
        st = self.status()
        if not st["ready"]:
            raise ProviderError(st["reason"])
        return self._cred["access_token"]

    def __repr__(self):
        return f"VertexAuth(project={self.project!r}, " \
               f"location={self.location!r})"
