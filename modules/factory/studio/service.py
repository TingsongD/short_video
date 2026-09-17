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
    def __init__(self, db, registry=None, launcher=None, cleanup=None):
        self.db = db
        self.cleanup = cleanup
        self.registry = registry          # F26 ResourceRegistry
        self.launcher = launcher          # callable → session info

    # ---------------------------------------------------- sessions --

    def open_session(self, session_id, composition_ws, owner,
                     media=()):
        """Open an owned preview session through the pinned launcher.
        The process registers with identity evidence; the lease is
        recorded so cleanup can stop it without touching others."""
        old=self._get(f"studio_session:{session_id}")
        if old and old.get("state")=="open":
            from ...batch.local import process_table,same_process
            resource=self.registry.get(f"studio-{session_id}") if self.registry else None
            if resource and same_process(resource,process_table().get(resource['pid'])):
                return {"session_id":session_id,**old}
            if hasattr(self.launcher,'launch'):
                raise ContractError('studio_session_unresolved','session_id','Close the saved session to verify cleanup before reopening')
        if self.launcher:
            if hasattr(self.launcher,"launch"):
                info = self.launcher.launch(composition_ws,owner,session_id)
            else:
                info = self.launcher(composition_ws)  # {pid,birth,command,port}
        else:
            raise ContractError("studio_unavailable","launcher","configure the qualified local launcher")
        if self.registry and info['pid']:
            prior=self.registry.get(f"studio-{session_id}")
            if prior and prior['pid']!=info['pid']:
                if prior['status']!='stopped':raise ContractError('studio_identity_conflict','session_id')
                with self.db.uow() as u:
                    u.events.append('factory','studio_previous_identity',prior)
                    u.conn.execute("DELETE FROM records WHERE kind='resource' AND id=?",(f'studio-{session_id}',))
        if self.registry and info["pid"] and not self.registry.get(f"studio-{session_id}"):
            self.registry.register(
                f"studio-{session_id}", info["pid"], info["birth"],
                info["command"], owner, cls="per_job",
                ports=(info.get("port"),) if info.get("port") else ())
        body = {"session_id": session_id, "owner": owner,
                "composition_ws": info.get("workspace",composition_ws),
                "url":info.get("url"),
                "media": list(media), "state": "open",
                "opened_at": _now(), "pid": info["pid"],
                "port": info.get("port")}
        self._put(f"studio_session:{session_id}", body)
        return {"session_id": session_id, "state": "open",
                "port": info.get("port"),"url":info.get("url")}

    def close_session(self, session_id):
        body = self._get(f"studio_session:{session_id}")
        if body is None:
            raise ContractError("not_found", "session_id", session_id)
        if not self.registry:
            raise ContractError("studio_unavailable","registry")
        from ..resources.service import CleanupService
        cleanup=self.cleanup or CleanupService(self.registry)
        ids={f"studio-{session_id}"} | {r["id"] for r in self.registry.for_owner(body["owner"]) if r.get("workspace")==body["composition_ws"]}
        receipt=cleanup.cleanup(body["owner"],resource_ids=ids)
        if receipt["state"]!="verified":
            return {"session_id":session_id,"state":"blocked","cleanup":receipt}
        self.registry.set_status(f"studio-{session_id}", "stopped")
        if hasattr(self.launcher,'closed'):self.launcher.closed(session_id)
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
            prior=u.records.get(kind,rid.split(':',1)[-1])
            revision=prior['revision']+1 if prior else 0
            u.conn.execute(
                "INSERT INTO records(kind,id,revision,schema_version,"
                "status,body,created_at,updated_at,version)"
                " VALUES(?,?,?,?,?,?,?,?,1)",
                (kind, rid.split(":", 1)[-1], revision,f"{kind}.v1",
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
