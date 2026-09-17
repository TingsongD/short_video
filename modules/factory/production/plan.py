"""Production service (F21): accepted experiment → priced unique-work
DAG persisted durably, scheduled through F06, recoverable by identity.

Every node is a WorkItem row; shared requests are one node, one price,
many consumers. Compose/deliver nodes are planned now and executed by
F22/F25 — they stay queued until their handlers exist.
"""
import json

from ..domain.errors import ContractError
from ..domain.records import Job, ProductionPlan, WorkItem, content_hash
from ..planning.asset_graph import (build_graph, canonical_request_key,
                                    downstream_blocked, expand_take,
                                    readiness)

PHASE_BY_KIND = {"picture": "generate_jimeng", "download": "collect",
                 "review": "review", "compose": "render",
                 "deliver": "deliver"}
EXECUTABLE = {"picture", "download", "review"}   # compose/deliver: F22+


class ProductionService:
    def __init__(self, db, scheduler=None, executor=None, adapter=None,
                 artifacts=None, selector=None, budget=None):
        self.db = db
        self.scheduler = scheduler
        self.executor = executor
        self.adapter = adapter
        self.artifacts = artifacts
        # selector(work_node) -> "accept"|"reject"|"uncertain"; default
        # accepts every downloaded work (fake-provider runs)
        self.selector = selector or (lambda n: "accept")
        self.budget = budget

    # ---------------------------------------------------------- build

    def plan(self, plan_id, experiment_id, revision, takes, provider,
             model, durations, variants=None, now=""):
        """takes: [{variant,slot,duration_s,request,handle_s?}].
        request is the canonical dict {prompt,settings,refs,audio}."""
        g = build_graph(plan_id, takes, provider, model, durations)
        plan = ProductionPlan(
            schema_version="production_plan.v1", id=plan_id,
            created_at=now, experiment_id=experiment_id,
            experiment_revision=revision, revision=1, status="draft",
            stats=g["stats"], variants=variants or sorted(
                {t["variant"] for t in takes}))
        # price each unique picture once, whatever its consumer count
        totals = {}
        for n in g["nodes"].values():
            if n["kind"] != "picture" or n["status"] == "needs_manual":
                continue
            amount = 0
            unit = ""
            if self.adapter is not None:
                for a in n["allocations"]:
                    m = self.adapter.price(n["request"],
                                           a["duration_s"], model)
                    m = m.to_dict() if hasattr(m, "to_dict") else m
                    a["price"] = m
                    amount += m["amount"]
                    unit = m["unit"]
            n["price"] = {"unit": unit, "amount": amount}
            if unit:
                totals[unit] = totals.get(unit, 0) + amount
        plan.total_price = totals
        plan.plan_hash = content_hash(
            {k: {"kind": n["kind"], "hash": n.get("request_hash", ""),
                 "consumers": n["consumers"], "depends": n["depends"]}
             for k, n in g["nodes"].items()})
        plan.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(plan)
            for n in g["nodes"].values():
                w = self._work_from_node(plan_id, n, now)
                u.records.put(w)
            u.events.append(f"plan:{plan_id}", "planned",
                            {"stats": plan.stats,
                             "total_price": totals})
        return {"plan": plan.to_dict(),
                "nodes": {k: v for k, v in g["nodes"].items()}}

    def _work_from_node(self, plan_id, n, now):
        return WorkItem(schema_version="work_item.v1",
                        id=f"{plan_id}:{n['node_key']}", created_at=now,
                        plan_id=plan_id, kind=n["kind"],
                        node_key=n["node_key"],
                        request_hash=n.get("request_hash", ""),
                        takes=n.get("takes", []),
                        consumers=n.get("consumers", []),
                        allocations=n.get("allocations", []),
                        provider=n.get("provider", ""),
                        model=n.get("model", ""),
                        request=n.get("request", {}),
                        price=n.get("price", {}),
                        status=n.get("status", "planned"),
                        depends=n.get("depends", []),
                        problem=n.get("problem", ""))

    def authorize(self, plan_id, authorization, account, budget_ids, valid_until):
        """Approve exact plan operations after the operator reviews its quote."""
        from ..execution.effects import EffectService, wire_hash
        from ..domain.records import PriceAssessment
        from ..store.uow import utcnow
        ops = []
        for key, node in self._nodes(plan_id).items():
            if node["kind"] != "picture" or node["status"] == "needs_manual":
                continue
            for i, allocation in enumerate(node["allocations"]):
                req = dict(node["request"], duration_s=allocation["duration_s"], model=node["model"])
                price = allocation.get("price")
                if not price or not price.get("unit"):
                    raise ContractError("no_price_assessment", "node", key)
                quote = PriceAssessment(schema_version="price_assessment.v1",
                    id=f"quote:{content_hash([authorization.id,key,i])[:32]}", created_at=utcnow(),
                    kind="usage_estimate" if node["provider"] == "google_vertex" else "native_quote",
                    request_hash=wire_hash(req), plan_hash=self._plan(plan_id)["plan_hash"],
                    provider=node["provider"], model=node["model"], unit=price["unit"],
                    amount=price["amount"], reserve_amount=price["amount"],
                    rate_basis="adapter:plan-quote", valid_until=valid_until)
                ops.append(dict(key=f"{key}:{i}", kind="generation", provider=node["provider"],
                    model=node["model"], account=account, request=req, price=quote))
        EffectService(self.db, self.executor).approve(authorization, "productionplan", plan_id, ops, budget_ids)
        return authorization.id

    def _authority(self, plan_id):
        rows = self.db.conn.execute("SELECT id FROM records WHERE kind='authorization' AND status='authorized' AND json_extract(body,'$.binding.kind')='productionplan' AND json_extract(body,'$.binding.id')=? ORDER BY created_at DESC", (plan_id,)).fetchall()
        if not rows:
            raise ContractError("authority_required", "plan_id", plan_id)
        return rows[0]["id"]

    # --------------------------------------------------------- submit

    def submit(self, plan_id):
        """Register every node as an F06 job (depends_on = dep job ids).
        Shared work submits once — consumers share the charge."""
        nodes = self._nodes(plan_id)
        jobs = []
        for key, n in nodes.items():
            phase = PHASE_BY_KIND[n["kind"]]
            if n["kind"] == "picture" and n.get("provider"):
                phase = ("generate_vertex" if "vertex" in n["provider"]
                         else "generate_jimeng")
            jobs.append(Job(
                schema_version="job.v1",
                id=f"{plan_id}:{key}", created_at="",
                logical_key=f"{plan_id}:{key}", phase=phase,
                experiment_id=self._plan(plan_id)["experiment_id"],
                revision=1,
                variant_key=(n["consumers"][0]
                             if len(n.get("consumers", [])) == 1 else ""),
                depends_on=[f"{plan_id}:{d}" for d in n["depends"]],
                status="waiting_dependencies",
                retry_class="bounded_paid" if n["kind"] == "picture"
                else "transfer" if n["kind"] == "download" else "none"))
        return self.scheduler.submit_plan(jobs)

    # -------------------------------------------------------- execute

    def run_next(self):
        """Claim one ready dispatch job and execute its node handler.
        Returns the node outcome or None."""
        job = self.scheduler.claim("collect") or self.scheduler.claim()
        if job is None:
            return None
        plan_id, key = job["logical_key"].split(":", 1)
        node = self._node(plan_id, key)
        if node["status"] in ("blocked", "rejected"):
            self.scheduler.fail(job["id"], job["fencing_token"],
                                f"work_{node['status']}")
            return {"node": key, "outcome": "blocked"}
        try:
            with self.scheduler.heartbeat(job["id"], job["fencing_token"]):
                outcome = self._execute(plan_id, node, job)
        except ContractError as e:
            if e.code in {"remote_unfinished", "capacity_full"}:
                self.scheduler.defer(job["id"], job["fencing_token"], e.code)
                return {"node": key, "outcome": "waiting", "error": e.code}
            self.scheduler.fail(job["id"], job["fencing_token"], e.code)
            return {"node": key, "outcome": "failed", "error": e.code}
        if outcome == "awaiting_review":
            self.scheduler.transition(job["id"], job["fencing_token"],
                                      "awaiting_review")
            return {"node": key, "outcome": outcome}
        self.scheduler.complete(job["id"], job["fencing_token"])
        return {"node": key, "outcome": outcome}

    def _execute(self, plan_id, node, job=None):
        kind = node["kind"]
        if kind == "picture":
            if node["status"] == "needs_manual":
                raise ContractError("needs_manual_coverage", "node",
                                    node["node_key"])
            op_ids = []
            from ..domain.money import Money
            priced = node.get("price") or {}
            from ..execution.effects import EffectService
            if job is None:
                raise ContractError("worker_lease_required", "job")
            effects = EffectService(self.db, self.executor)
            authority_id = self._authority(plan_id)
            for i, a in enumerate(node["allocations"]):
                req = dict(node["request"], duration_s=a["duration_s"], model=node["model"])
                att = effects.prepare(authority_id, f"{node['node_key']}:{i}",
                    job["id"], job["fencing_token"], self.scheduler.worker_id, i + 1)
                price = Money(**a["price"])
                op = self.executor.submit(
                    att, lambda: self.adapter.submit(req, price=price))
                op_ids.append(op["operation_id"])
            self._set(plan_id, node["node_key"], status="submitted",
                      operation_id=";".join(op_ids))
            return "submitted"
        if kind == "download":
            pic_key = node["depends"][0]
            pic = self._node(plan_id, pic_key)
            if pic["status"] == "manual":
                self._set(plan_id, node["node_key"],
                          status="downloaded",
                          artifact_ids=pic["artifact_ids"])
                return "downloaded"
            artifact_ids = []
            atts = self.db.conn.execute(
                "SELECT id FROM attempts WHERE job_id=? ORDER BY id",
                (f"{plan_id}:{pic_key}",)).fetchall()
            for a in atts:
                op = self.executor.poll(a["id"])
                if op.get("status") in {"failed", "cancelled"}:
                    raise ContractError("remote_terminal_failure", "attempt", a["id"])
                if op.get("status") != "succeeded":
                    raise ContractError("remote_unfinished", "attempt",
                                        a["id"])
                dl = self.executor.download(a["id"])
                art = self.artifacts.intake_bytes(
                    dl["bytes"], provenance=pic["provider"],
                    source_key=f"gen:{a['id']}",
                    source_detail=f"plan:{plan_id}",
                    requested_kind="video")
                artifact_ids.append(art.id)
            # remote ops finished → the submit-slot hold releases
            with self.db.uow() as u:
                u.conn.execute(
                    "DELETE FROM capacity_holds WHERE job_id=?",
                    (f"{plan_id}:{pic_key}",))
            self._set(plan_id, node["node_key"], status="downloaded",
                      artifact_ids=artifact_ids)
            self._set(plan_id, pic_key, status="downloaded")
            return "downloaded"
        if kind == "review":
            variant = node["consumers"][0]
            verdicts = {}
            for dep in node["depends"]:
                pic_key = self._node(plan_id, dep)["depends"][0]
                pic = self._node(plan_id, pic_key)
                verdict = self.selector(pic)
                verdicts[pic_key] = verdict
                if verdict == "reject":
                    self._set(plan_id, pic_key, status="rejected",
                              problem="review_rejected")
                elif verdict == "accept":
                    self._set(plan_id, pic_key, status="accepted")
                else:
                    self._set(plan_id, pic_key, status="uncertain")
            if any(v == "reject" for v in verdicts.values()):
                self._set(plan_id, node["node_key"], status="rejected",
                          problem=json.dumps(verdicts))
                raise ContractError("review_rejected", "variant",
                                    variant)
            if any(v == "uncertain" for v in verdicts.values()):
                self._set(plan_id, node["node_key"], status="reviewing",
                          problem=json.dumps(verdicts))
                return "awaiting_review"
            self._set(plan_id, node["node_key"], status="done")
            return "reviewed"
        raise ContractError("handler_unavailable", "kind", kind)

    # ------------------------------------------------- branch control

    def reject_work(self, plan_id, node_key, reason="rejected"):
        """Reject one work node: only chains consuming it block —
        shared accepted assets and other variants stay intact."""
        nodes = self._nodes(plan_id)
        if node_key not in nodes:
            raise ContractError("unknown_node", "node_key", node_key)
        affected = set(nodes[node_key].get("consumers", []))
        self._set(plan_id, node_key, status="rejected", problem=reason)
        # block downstream nodes only where every consumer is affected
        changed = True
        while changed:
            changed = False
            for k, n in nodes.items():
                if k == node_key or n["status"] in ("blocked",
                                                    "rejected"):
                    continue
                deps = set(n.get("depends", []))
                dep_states = {self._node(plan_id, d)["status"]
                              for d in deps if self._node(plan_id, d)}
                if node_key in deps or "rejected" in dep_states \
                        or "blocked" in dep_states:
                    if set(n.get("consumers", [])) <= affected:
                        self._set(plan_id, k, status="blocked",
                                  problem=f"upstream {reason}")
                        nodes[k]["status"] = "blocked"
                        changed = True
        return {"rejected": node_key, "blocked_variants":
                sorted(affected)}

    def replace_manual(self, plan_id, node_key, artifact_id):
        """Manual coverage for a needs_manual/rejected node: same
        coverage + provenance checks as generated work."""
        node = self._node(plan_id, node_key)
        row = self.db.uow().artifacts.get(artifact_id)
        if row is None:
            raise ContractError("unknown_artifact", "artifact_id",
                                artifact_id)
        if row["provenance"] not in ("manual", "stock"):
            raise ContractError("bad_provenance", "provenance",
                                row["provenance"])
        probe = json.loads(row["probe"] or "{}")
        need = max((t["duration_s"] for t in node.get("takes", [])
                    ), default=0)
        if row["kind"] != "video" or row["status"] != "registered":
            raise ContractError("invalid_manual_video", "artifact_id", artifact_id)
        have = probe.get("duration_s") or 0
        if have + 1e-6 < need:
            raise ContractError("insufficient_coverage", "duration_s",
                                f"need {need}s, artifact has {have}s")
        self._set(plan_id, node_key, status="manual",
                  artifact_ids=[artifact_id])
        # unblock its download node — manual coverage feeds it directly
        for k, n in self._nodes(plan_id).items():
            if node_key in n.get("depends", []):
                self._set(plan_id, k, status="downloaded",
                          artifact_ids=[artifact_id])
        with self.db.uow() as u:
            jid = f"{plan_id}:{node_key}"
            u.conn.execute("UPDATE jobs SET status='succeeded',blocked_reason=NULL,lease_owner=NULL,lease_expires=NULL WHERE id=?", (jid,))
            remaining = {k for k in self._nodes(plan_id) if k != node_key}
            repaired = {node_key}
            while True:
                children = [k for k in remaining if set(self._node(plan_id,k)["depends"]) & repaired]
                if not children:
                    break
                for key in children:
                    remaining.remove(key)
                    repaired.add(key)
                    child = self._node(plan_id,key)
                    if child["kind"] == "download":
                        status = "succeeded"
                    else:
                        status = "waiting_dependencies"
                        self._set(plan_id,key,status="planned",problem="")
                    u.conn.execute("UPDATE jobs SET status=?,blocked_reason=NULL,lease_owner=NULL,lease_expires=NULL,next_attempt_at=NULL,retry_count=0 WHERE id=? AND status IN ('blocked','failed','awaiting_review','ready','waiting_dependencies')", (status, f"{plan_id}:{key}"))
            u.events.append(f"plan:{plan_id}", "manual_replacement", {"node": node_key, "artifact": artifact_id, "downstream": sorted(repaired)})
        return {"status": "manual", "artifact_id": artifact_id}

    # --------------------------------------------------------- status

    def status(self, plan_id):
        return {"plan": self._plan(plan_id),
                "readiness": readiness(self._nodes(plan_id))}

    def resume(self, plan_id):
        """Restart view: persisted work states drive remaining jobs —
        downloaded/accepted assets are never regenerated."""
        if self.scheduler:
            self.scheduler.resume(self._plan(plan_id)["experiment_id"])
            self.scheduler.reclaim_expired()
        if self.executor:
            self.executor.recover()
        return self.status(plan_id)

    # --------------------------------------------------------- helpers

    def _plan(self, plan_id):
        row = self.db.uow().records.get("productionplan", plan_id)
        return json.loads(row["body"]) if row else None

    def _nodes(self, plan_id):
        rows = self.db.conn.execute(
            "SELECT id, body FROM records WHERE kind='workitem' "
            "AND json_extract(body,'$.plan_id')=?",
            (plan_id,)).fetchall()
        return {json.loads(r["body"])["node_key"]:
                json.loads(r["body"]) for r in rows}

    def _node(self, plan_id, key):
        row = self.db.uow().records.get("workitem", f"{plan_id}:{key}")
        if row is None:
            raise ContractError("unknown_node", "node_key", key)
        return json.loads(row["body"])

    def _set(self, plan_id, key, **fields):
        row = self.db.uow().records.get("workitem", f"{plan_id}:{key}")
        body = json.loads(row["body"])
        body.update(fields)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='workitem' "
                "AND id=? AND revision=?",
                (json.dumps(body), f"{plan_id}:{key}", row["revision"]))
