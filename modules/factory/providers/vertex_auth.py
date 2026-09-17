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
        self._load()

    def _load(self):
        try:
            self._cred = self._loader()
        except AuthError as e:
            self._cred = {"kind": "error", "reason": e.reason}
        except Exception:
            self._cred = {"kind": "error", "reason": "loader_failed"}

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
        except ValueError:
            return False
        return when <= self._now()

    def status(self):
        """Readiness only — never carries the token."""
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
        st = self.status()
        if not st["ready"]:
            raise ProviderError(st["reason"])
        return self._cred["access_token"]

    def __repr__(self):
        return f"VertexAuth(project={self.project!r}, " \
               f"location={self.location!r})"
