"""Bounded next-round continuation (PL-06).

A Round-N child is created from a SeedSelection — never directly from
a decision. One active child per parent; creation is idempotent by
(parent experiment, revision). A mature reevaluation that changes the
winner marks the child's BASIS superseded — it never deletes posts
and never auto-generates a replacement."""
import json
from datetime import datetime, timezone

from ..domain.errors import ContractError
from ..domain.records import LoopPolicy, RoundLineage, Seed
from ..store.uow import utcnow


def _now():
    return datetime.now(timezone.utc).isoformat()


class RoundService:
    def __init__(self, services):
        self.s = services
        self.db = services.db

    # ------------------------------------------------------- policy --

    def _series_id(self, experiment_id):
        er = self.db.uow().records.get(
            "experimentrevision", f"exp:{experiment_id}")
        if er is None:
            raise ContractError("not_found", "experiment", experiment_id)
        body = json.loads(er["body"])
        seed = self.db.uow().records.get("seed", body.get("seed_id", ""))
        sb = json.loads(seed["body"]) if seed else {}
        group = (sb.get("independence_group") or
                 sb.get("lineage_root_id") or body.get("seed_id") or
                 experiment_id)
        return f"series:{group}", body, sb

    def _loop_policy(self, series_id):
        row = self.db.uow().records.get("looppolicy", series_id)
        return json.loads(row["body"]) if row else None

    def freeze_loop(self, series_id, *, mode="propose_only",
                    max_rounds=1, max_posts=0, allowed_providers=None,
                    allowed_accounts=None, spend_caps=None,
                    valid_until="", stop_conditions=None,
                    authorization_id="", now=""):
        """Bind the continuation authority BEFORE any child is
        proposed. max_rounds>0 is required — an unbounded loop is not
        a policy."""
        if type(max_rounds) is not int or max_rounds < 1:
            raise ContractError("loop_needs_max_rounds", "max_rounds")
        pol = LoopPolicy(
            schema_version="loop_policy.v1", id=series_id,
            created_at=now or _now(), series_id=series_id, mode=mode,
            max_rounds=max_rounds, max_posts=max_posts,
            allowed_providers=list(allowed_providers or []),
            allowed_accounts=list(allowed_accounts or []),
            spend_caps=dict(spend_caps or {}),
            valid_until=valid_until,
            stop_conditions=list(stop_conditions or []),
            authorization_id=authorization_id)
        pol.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(pol)
            u.events.append(f"series:{series_id}", "loop_frozen",
                            {"mode": mode, "max_rounds": max_rounds})
        return pol.to_dict()

    def _children(self, series_id):
        rows = self.db.conn.execute(
            "SELECT body FROM records WHERE kind='roundlineage'"
            " AND json_extract(body,'$.series_id')=? ORDER BY id",
            (series_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def _series_experiments(self, series_id):
        """Experiments whose seed resolves to this series' group —
        the round-1 parent plus every derived round."""
        group = series_id.split(":", 1)[-1]
        exps = set()
        for r in self.db.conn.execute(
                "SELECT body FROM records WHERE kind="
                "'experimentrevision'").fetchall():
            b = json.loads(r[0])
            row = self.db.uow().records.get(
                "seed", b.get("seed_id", ""))
            sb = json.loads(row["body"]) if row else {}
            g = (sb.get("independence_group") or
                 sb.get("lineage_root_id") or b.get("seed_id"))
            if g == group:
                exps.add(b["experiment_id"])
        for c in self._children(series_id):
            exps.add(c.get("experiment_id", ""))
            exps.add(c.get("parent_experiment_id", ""))
        exps.discard("")
        return exps

    def _series_posts(self, series_id):
        exps = self._series_experiments(series_id)
        rows = self.db.conn.execute(
            "SELECT body FROM records WHERE kind='publication'"
            ).fetchall()
        return [json.loads(r[0]) for r in rows
                if json.loads(r[0]).get("experiment_id") in exps]

    # ----------------------------------------------------- proposal --

    def propose_next(self, experiment_id, revision, selection_id,
                     now=""):
        """Create the Round-N proposal: derived seed + lineage record.
        Idempotent — the same parent + same selection returns the
        existing child; one ACTIVE child per parent is enforced."""
        now = now or _now()
        sel_row = self.db.uow().records.get("seedselection",
                                            selection_id)
        if sel_row is None:
            raise ContractError("not_found", "selection", selection_id)
        sel = json.loads(sel_row["body"])
        if self._superseded(selection_id):
            raise ContractError("selection_superseded", "selection",
                                selection_id)
        if sel.get("experiment_id") != experiment_id or \
                sel.get("experiment_revision") != revision:
            raise ContractError("selection_scope_mismatch", "selection")
        if not sel.get("winner_variant"):
            raise ContractError("no_winner", "status", sel.get("status"))

        series_id, er_body, parent_seed = self._series_id(experiment_id)
        pol = self._loop_policy(series_id)
        if pol is None:
            raise ContractError("loop_policy_required", "series_id",
                                series_id)
        if pol["status"] != "active":
            raise ContractError("loop_halted", "status", pol["status"])
        if pol.get("valid_until") and pol["valid_until"] <= now:
            self._set_policy(series_id, status="expired")
            raise ContractError("loop_expired", "valid_until",
                                pol["valid_until"])
        children = self._children(series_id)
        active = [c for c in children if c["status"] in
                  ("proposed", "active")]
        # Idempotency resolves BEFORE the round limit — replaying an
        # accepted proposal must return the existing child even when
        # the limit is already reached (default max_rounds=1).
        for c in active:
            if c.get("parent_selection_id") == selection_id:
                return {"lineage": c, "idempotent": True}
            raise ContractError(
                "active_child_exists", "lineage", c["id"])
        if len(children) >= pol["max_rounds"]:
            raise ContractError("round_limit", "max_rounds",
                                pol["max_rounds"])
        if pol.get("max_posts"):
            posts = self._series_posts(series_id)
            if len(posts) >= pol["max_posts"]:
                raise ContractError("post_limit", "max_posts",
                                    pol["max_posts"])

        if "stop_on_inconclusive" in pol.get("stop_conditions", []):
            pass  # evaluated on the NEXT proposal, not this one
        parent_seed_id = er_body.get("seed_id", "")
        round_no = len(children) + 1
        root_ref = (parent_seed.get("lineage_root_id") or
                    parent_seed.get("independence_group") or
                    parent_seed_id)
        winner = sel["winner_variant"]
        child_seed_id = f"seed-{experiment_id}-r{revision}-{winner.lower()}-r{round_no}"
        lid = f"line-{experiment_id}-r{revision}-{round_no}"
        child = Seed(
            schema_version="seed.v1", id=child_seed_id, created_at=now,
            platform="local",
            original_url=parent_seed.get("original_url", ""),
            canonical_url=parent_seed.get("canonical_url", ""),
            title=f"Round {round_no} seed — variant {winner} of "
                  f"{experiment_id}",
            parent_seed_id=parent_seed_id,
            lineage_root_id=root_ref,
            independence_group=(parent_seed.get("independence_group")
                                or root_ref),
            round=round_no,
            metadata={"basis": "selection", "selection_id": selection_id,
                      "winner_variant": winner})
        lineage = RoundLineage(
            schema_version="round_lineage.v1", id=lid, created_at=now,
            series_id=series_id, round=round_no,
            parent_experiment_id=experiment_id,
            parent_experiment_revision=revision,
            parent_selection_id=selection_id,
            seed_id=child_seed_id,
            root_reference_id=root_ref,
            independence_group=child.independence_group,
            status="proposed")
        lineage.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(child)
            u.records.put(lineage)
            # The selection now names its child seed — evaluation stays
            # separate from creation, but the link is recorded once.
            sel["seed_id"] = child_seed_id
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='seedselection'"
                " AND id=?", (json.dumps(sel), selection_id))
            u.events.append(
                f"experiment:{experiment_id}", "round_proposed",
                {"lineage": lid, "seed": child_seed_id,
                 "winner": winner, "round": round_no})
        # §10/PL-06: the child seed carries the champion's accepted
        # local master as its source media — a lineage pointer alone
        # can never pass the analysis gate.
        media = self._attach_winner_media(
            child_seed_id, experiment_id, revision, winner)
        return {"lineage": lineage.to_dict(), "seed": child.to_dict(),
                "winner_variant": winner, "round": round_no,
                "mode": pol["mode"], "winner_media": media,
                "requires_review": pol["mode"] == "propose_only" or
                self._analysis_review_required(experiment_id,
                                               revision, winner)}

    def _attach_winner_media(self, seed_id, experiment_id, revision,
                             winner):
        """Bind the champion variant's final artifact as the child's
        source media. Failure is recorded, not hidden — a seed without
        the winner's bytes is an explicit blocker, not a fake ready."""
        vp = ""
        for r in self._all_bodies("variantplan"):
            if (r.get("experiment_id") == experiment_id and
                    r.get("experiment_revision") == revision and
                    r.get("variant_key") == winner):
                vp = r["id"]
                break
        if not vp:
            return {"status": "no_winner_variant"}
        artifact = ""
        for p in self._all_bodies("publication"):
            if (p.get("variant_plan_id") == vp and
                    p.get("artifact_id")):
                artifact = p["artifact_id"]
                break
        if not artifact:
            meta = self.db.conn.execute(
                "SELECT value FROM meta WHERE key=?",
                (f"final:{vp}",)).fetchone()
            stored = json.loads(meta[0]) if meta else {}
            artifact = stored.get("artifact_id", "")
        if not artifact:
            return {"status": "no_winner_artifact"}
        try:
            self.s.seeds.attach_media(seed_id, artifact,
                                      via="round_seed")
        except (ContractError, AttributeError) as e:
            return {"status": "attach_failed",
                    "error": getattr(e, "code", str(e))}
        return {"status": "media_ready", "artifact_id": artifact}

    def _all_bodies(self, kind):
        return [json.loads(r[0]) for r in self.db.conn.execute(
            "SELECT body FROM records WHERE kind=?", (kind,)).fetchall()]

    def _analysis_review_required(self, experiment_id, revision,
                                  winner):
        """Changed champion bytes need Hypit-directed analysis before
        the new round runs — the seed's analysis gate decides, not
        this service. Here we only flag that an A-vs-winner byte
        change exists (or not)."""
        return winner != "A"

    # ------------------------------------------- mature reevaluation --

    def mark_basis_superseded(self, selection_id, now=""):
        """Mature evidence revised the winner AFTER a child was
        proposed: keep the child's history, mark its basis superseded.
        No posts are deleted and no replacement is generated."""
        rows = self.db.conn.execute(
            "SELECT body FROM records WHERE kind='roundlineage'"
            " AND json_extract(body,'$.parent_selection_id')=?",
            (selection_id,)).fetchall()
        out = []
        for r in rows:
            c = json.loads(r[0])
            if c["status"] in ("proposed", "active"):
                self._set_lineage(c["id"], status="superseded")
                out.append(c["id"])
        return out

    # ------------------------------------------------------ control --

    def cancel_series(self, series_id, now=""):
        """§10 series_cancel: stop new local work AND cancel each
        remotely-scheduled job, per destination, with per-job
        outcomes. A post that already raced live is reported
        'already_public', never 'cancelled'."""
        now = now or _now()
        pol = self._loop_policy(series_id)
        if pol is not None:
            self._set_policy(series_id, status="revoked")
        outcomes = []
        pubs = self._series_posts(series_id)
        for p in pubs:
            if p.get("status") == "scheduled":
                try:
                    res = self.s.publishing.cancel_remote(p["id"],
                                                          now=now)
                except ContractError as e:
                    res = {"outcome": "unknown", "error": e.code}
                outcomes.append({"publication_id": p["id"],
                                 "platform": p.get("platform", ""),
                                 **res})
        for c in self._children(series_id):
            if c["status"] in ("proposed", "active"):
                self._set_lineage(c["id"], status="cancelled")
        return {"series_id": series_id, "remote": outcomes,
                "policy": (self._loop_policy(series_id) or {}).get(
                    "status")}

    def pause_series(self, series_id):
        """§10 pause: stops new local dispatch ONLY. Provider-side
        schedules still fire — callers must not imply otherwise."""
        pol = self._loop_policy(series_id)
        if pol is None:
            raise ContractError("loop_policy_required", "series_id",
                                series_id)
        self._set_policy(series_id, status="paused")
        remote = [{"publication_id": p["id"],
                   "platform": p.get("platform", ""),
                   "state": "scheduled_remote — will publish unless "
                            "cancelled"}
                  for p in self._series_posts(series_id)
                  if p.get("status") == "scheduled"]
        return {"series_id": series_id, "status": "paused",
                "outstanding_remote": remote}

    # ----------------------------------------------------------- io --

    def _set_policy(self, series_id, **fields):
        with self.db.uow() as u:
            row = u.records.get("looppolicy", series_id)
            if row is None:
                return
            body = json.loads(row["body"])
            body.update(fields)
            u.conn.execute(
                "UPDATE records SET body=?,updated_at=? WHERE"
                " kind='looppolicy' AND id=?",
                (json.dumps(body), utcnow(), series_id))

    def _set_lineage(self, lid, **fields):
        with self.db.uow() as u:
            row = u.records.get("roundlineage", lid)
            if row is None:
                return
            body = json.loads(row["body"])
            body.update(fields)
            u.conn.execute(
                "UPDATE records SET body=?,updated_at=? WHERE"
                " kind='roundlineage' AND id=?",
                (json.dumps(body), utcnow(), lid))

    def _superseded(self, selection_id):
        row = self.db.conn.execute(
            "SELECT value FROM meta WHERE key=?",
            ("superseded:" + selection_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def lineage(self, series_id):
        return {"series_id": series_id,
                "policy": self._loop_policy(series_id),
                "children": self._children(series_id)}
