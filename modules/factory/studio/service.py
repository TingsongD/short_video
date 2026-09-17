"""Hypit Studio preview sessions + feedback (F29).

A session is an OWNED resource (F26 registry) — it can be stopped
safely and never outlives its lease silently. Imported comments map
to an exact timeline position and plan revision, producing a proposed
change with an explicit diff/cost — never immediate paid regeneration.
"""
import json
from datetime import datetime, timezone

from ..domain.errors import ContractError


def _now():
    return datetime.now(timezone.utc).isoformat()


class StudioService:
    def __init__(self, db, registry=None, launcher=None):
        self.db = db
        self.registry = registry          # F26 ResourceRegistry
        self.launcher = launcher          # callable → session info

    # ---------------------------------------------------- sessions --

    def open_session(self, session_id, composition_ws, owner,
                     media=()):
        """Open an owned preview session through the pinned launcher.
        The process registers with identity evidence; the lease is
        recorded so cleanup can stop it without touching others."""
        if self.launcher:
            info = self.launcher(composition_ws)  # {pid,birth,command,port}
        else:
            info = {"pid": 0, "birth": "simulated", "command":
                    "hypit studio (launcher not wired)", "port": 0}
        if self.registry and info["pid"]:
            self.registry.register(
                f"studio-{session_id}", info["pid"], info["birth"],
                info["command"], owner, cls="per_job",
                ports=(info.get("port"),) if info.get("port") else ())
        body = {"session_id": session_id, "owner": owner,
                "composition_ws": composition_ws,
                "media": list(media), "state": "open",
                "opened_at": _now(), "pid": info["pid"],
                "port": info.get("port")}
        self._put(f"studio_session:{session_id}", body)
        return {"session_id": session_id, "state": "open",
                "port": info.get("port")}

    def close_session(self, session_id):
        body = self._get(f"studio_session:{session_id}")
        if body is None:
            raise ContractError("not_found", "session_id", session_id)
        if self.registry:
            self.registry.set_status(f"studio-{session_id}", "stopped")
        self._set(f"studio_session:{session_id}", state="closed",
                  closed_at=_now())
        return {"session_id": session_id, "state": "closed"}

    # ----------------------------------------------------- comments --

    def import_comment(self, comment_id, variant_id, at_s, text,
                       source_revision, session_id=None):
        """A Studio comment becomes a PROPOSED CHANGE bound to the
        exact source revision — never an immediate regeneration."""
        if source_revision is None:
            raise ContractError("missing_revision", "source_revision",
                                "feedback must bind an exact revision")
        if session_id:
            sess = self._get(f"studio_session:{session_id}")
            if sess is None or sess["state"] != "open":
                raise ContractError("session_closed", "session_id",
                                    session_id)
        change = {"comment_id": comment_id, "variant_id": variant_id,
                  "at_s": at_s, "text": text,
                  "source_revision": source_revision,
                  "status": "proposed", "created_at": _now(),
                  "session_id": session_id,
                  "diff": {"region": {"at_s": at_s},
                           "action": "revise_segment",
                           "instruction": text},
                  "estimated_cost": "requires_quote"}
        self._put(f"proposed_change:{comment_id}", change)
        return {"id": comment_id, "status": "proposed",
                "bound_revision": source_revision}

    def mark_stale(self, comment_id, new_revision):
        """The reviewed revision moved — the proposal is stale until
        re-mapped, it can never silently fund the new revision."""
        body = self._get(f"proposed_change:{comment_id}")
        if body is None:
            raise ContractError("not_found", "comment_id", comment_id)
        self._set(f"proposed_change:{comment_id}", status="stale",
                  invalidated_by=new_revision)
        return {"id": comment_id, "status": "stale",
                "invalidated_by": new_revision}

    def proposed_changes(self, variant_id):
        rows = self.db.uow().conn.execute(
            "SELECT id,body FROM records WHERE kind='proposed_change'"
        ).fetchall()
        out = []
        for rid, b in rows:
            d = json.loads(b)
            if d["variant_id"] == variant_id:
                out.append({"id": rid.split(":", 1)[-1], **d})
        return out

    # ----------------------------------------------------------- db --

    def _put(self, rid, body):
        kind, _, _ = rid.partition(":")
        with self.db.uow() as u:
            u.conn.execute(
                "INSERT INTO records(kind,id,revision,schema_version,"
                "status,body,created_at,updated_at,version)"
                " VALUES(?,?,0,?,?,?,?,?,1)",
                (kind, rid.split(":", 1)[-1], f"{kind}.v1",
                 body.get("status", body.get("state", "")),
                 json.dumps(body), _now(), _now()))

    def _get(self, rid):
        kind, _, rid2 = rid.partition(":")
        row = self.db.uow().records.get(kind, rid2)
        return json.loads(row["body"]) if row else None

    def _set(self, rid, **fields):
        kind, _, rid2 = rid.partition(":")
        row = self.db.uow().records.get(kind, rid2)
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=?,status=? WHERE kind=? AND "
                "id=? AND revision=?",
                (json.dumps(body),
                 body.get("status", body.get("state", "")),
                 kind, rid2, row["revision"]))
