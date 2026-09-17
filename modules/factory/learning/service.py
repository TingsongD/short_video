"""Experiment decisions and learning library (F33): conservative,
auditable, reproducible.

- The decision policy is FROZEN before publication; `decide` refuses
  to run without one and `freeze_policy` refuses to bind after the
  experiment already has publications.
- Identical inputs reproduce the identical decision — `inputs_hash`
  covers the policy, evidence snapshot ids and observed metric
  values. New data produces a NEW revisioned decision; the old one is
  marked superseded, never rewritten.
- A=0 or insufficient exposure yields DEFINED handling
  (inconclusive/insufficient_exposure), never an infinite lift or an
  automatic winner.
- Four posts from one seed are ONE experiment: independent-seed
  counting is explicit, sibling variants cannot manufacture
  confirmations, and every summary is labelled observational — never
  causal.
"""
import hashlib
import json
from datetime import datetime, timezone

from ..domain.errors import ContractError
from ..domain.records import Decision, DecisionPolicy, Hypothesis


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(json.dumps(p, sort_keys=True, default=str).encode())
    return h.hexdigest()


LIMIT_OBSERVATIONAL = (
    "observational evidence from organic posting — descriptive, "
    "not a causal A/B claim")
LIMIT_SIBLINGS = (
    "sibling variants share one seed/control — this is one "
    "experiment, not independent confirmations")
LIMIT_MULTIPLE = "three treatment-vs-control comparisons; " \
    "multiplicity not corrected — descriptive ranking only"


class LearningService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------- policy --

    def freeze_policy(self, experiment_id, revision, *, policy_version,
                      primary_metric, horizon, min_exposure=0,
                      practical_lift=0.0, exposure_metric=
                      "thumbnail_impressions", guardrails=None,
                      comparison_rule="any",
                      promote_min_independent_experiments=2, now=""):
        """Bind the policy BEFORE any publication for the experiment."""
        now = now or _now()
        from ..analytics.service import HORIZONS,NORMALIZED
        if horizon not in HORIZONS or primary_metric not in NORMALIZED or primary_metric=='public_views' or exposure_metric not in NORMALIZED or exposure_metric=='public_views' or comparison_rule not in ('any','all'):
            raise ContractError('invalid_decision_policy','metric/horizon/rule')
        if type(promote_min_independent_experiments) is not int or promote_min_independent_experiments<2:raise ContractError('invalid_promotion_threshold','threshold')
        er=self._record('experimentrevision','exp:'+experiment_id)
        if not er or er['revision']!=revision:raise ContractError('stale_revision','experiment')
        for pub in self._all("publication"):
            body = json.loads(pub["body"])
            vp = self._record("variantplan",
                              body.get("variant_plan_id", ""))
            if vp and json.loads(vp["body"]).get(
                    "experiment_id") == experiment_id and \
                    body.get("status") not in ("failed",):
                raise ContractError(
                    "policy_after_publication", "experiment_id",
                    experiment_id)
        pid = f"pol-{experiment_id}-r{revision}"
        pol = DecisionPolicy(
            schema_version="decision_policy.v1", id=pid,
            created_at=now, experiment_id=experiment_id,
            experiment_revision=revision,
            policy_version=policy_version,
            primary_metric=primary_metric, horizon=horizon,
            exposure_metric=exposure_metric,
            min_exposure=min_exposure,
            practical_lift=practical_lift,
            guardrails=dict(guardrails or {}),
            comparison_rule=comparison_rule,
            promote_min_independent_experiments=
            promote_min_independent_experiments,
            status="frozen")
        pol.content_hash = _hash(
            experiment_id, revision,
            policy_version, primary_metric, horizon, exposure_metric,
            min_exposure, practical_lift, guardrails or {},
            comparison_rule,promote_min_independent_experiments)
        pol.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(pol)
            u.events.append(f"experiment:{experiment_id}",
                            "policy_frozen",
                            {"policy_version": policy_version})
        return pol

    def policy(self, experiment_id, revision):
        row = self._record("decisionpolicy",
                           f"pol-{experiment_id}-r{revision}")
        return json.loads(row["body"]) if row else None

    # ------------------------------------------------------- decide --

    def decide(self, experiment_id, revision, horizon="", now=""):
        """Compute the decision deterministically from stored
        evidence. Identical inputs → identical record (idempotent);
        changed inputs → a new decision revision."""
        now = now or _now()
        pol = self.policy(experiment_id, revision)
        if pol is None:
            raise ContractError("policy_not_frozen", "experiment_id",
                                experiment_id)
        if horizon and horizon!=pol['horizon']:raise ContractError('frozen_horizon','horizon')
        horizon = pol['horizon']
        from ..analytics.service import HORIZONS
        variants = self._variants(experiment_id, revision)
        if {v['variant_key'] for v in variants}!=set('ABCD'):
            raise ContractError("no_variants", "experiment_id",
                                experiment_id)
        control_key = "A"
        evidence, per_variant = [], {}
        for vp in variants:
            pub = self._publication_for(vp["id"])
            snap = self._snapshot(pub["id"], horizon) if pub else None
            entry = {"variant": vp["variant_key"],
                     "publication_id": (pub or {}).get("id", ""),
                     "snapshot_id": (snap or {}).get("id", ""),
                     "post_id": (pub or {}).get("remote_post_id", "")}
            if pub is None or snap is None:
                entry["coverage"] = "missing"
            else:
                entry["coverage"] = snap["completeness"]
                entry['metrics']={k:v for k,v in snap['metrics'].items() if snap.get('availability',{}).get(k) in ('ok','verified_manual')}
                entry['window']={'query_version':snap.get('query_version'),'timezone':snap.get('timezone'),
                    'hours':snap.get('requested_period',{}).get('horizon_hours'),'kind':snap.get('requested_period',{}).get('window_kind'),
                    'definitions':snap.get('metric_definitions',{}),'source':snap.get('source')}
                entry['snapshot_revision']=snap.get('revision',0)
                if entry['window']['kind']!='exact_rolling' or entry['window']['hours']!=HORIZONS[horizon]:entry['coverage']='incompatible_window'
            per_variant[vp["variant_key"]] = entry
            if snap:
                evidence.append(snap["id"])

        post_ids=[(v.get('post_id'),v.get('publication_id')) for v in per_variant.values()]
        if len({x[0] for x in post_ids if x[0]})!=len(per_variant):
            for v in per_variant.values():v['coverage']='missing_or_duplicate_post'
        comparisons, conclusion, winner, limitations = \
            self._evaluate(pol, per_variant, control_key)
        inputs_hash = _hash(
            pol["content_hash"], horizon,
            {k: {"snap": v.get("snapshot_id", ""),
                 "cov": v["coverage"],
                 "m": v.get("metrics", {}),"window":v.get("window"),"snapshot_revision":v.get("snapshot_revision"),"post_id":v.get("post_id")}
             for k, v in sorted(per_variant.items())})
        did = f"dec-{experiment_id}-r{revision}-{horizon}"
        priors = self._decision_chain(did)
        latest = priors[-1] if priors else None
        if latest and json.loads(latest["body"]).get(
                "inputs_hash") == inputs_hash:
            body = json.loads(latest["body"])
            body["_idempotent"] = True
            return body                         # identical → no new row
        if latest:
            new_id = f"{did}-v{len(priors)}"
            did = new_id
        dec = Decision(
            schema_version="decision.v1", id=did, created_at=now,
            experiment_id=experiment_id,
            experiment_revision=revision,
            policy_version=pol["policy_version"], horizon=horizon,
            primary_metric=pol["primary_metric"],
            comparisons=comparisons, conclusion=conclusion,
            winner=winner, evidence_ids=evidence,
            limitations=limitations, inputs_hash=inputs_hash)
        dec.validate_or_raise()
        with self.db.uow() as u:
            if latest:self._supersede(latest,did)
            u.records.put(dec)
            u.events.append(f"experiment:{experiment_id}",
                            "decision_computed",
                            {"decision": did, "conclusion": conclusion})
        out = dec.to_dict() if hasattr(dec, "to_dict") else dec.__dict__
        return out

    def _evaluate(self, pol, per_variant, control_key):
        limitations = [LIMIT_OBSERVATIONAL, LIMIT_SIBLINGS,
                       LIMIT_MULTIPLE]
        metric = pol["primary_metric"]
        missing = [k for k, v in per_variant.items()
                   if v["coverage"] != "complete"]
        if missing:
            return [], "waiting_for_data", "", limitations + [
                f"incomplete coverage: {sorted(missing)}"]
        import math
        windows={json.dumps(v.get('window'),sort_keys=True) for v in per_variant.values()}
        if len(windows)!=1:return [],'waiting_for_data','',limitations+['incompatible observation windows or source definitions']
        for key,v in per_variant.items():
            exposure=v.get('metrics',{}).get(pol['exposure_metric'])
            if type(exposure) not in (int,float) or not math.isfinite(exposure) or exposure<pol['min_exposure']:
                return [],'insufficient_exposure','',limitations+[f"{key}: {pol['exposure_metric']}={exposure}; each arm requires {pol['min_exposure']}"]
        if any(type(v.get('metrics',{}).get(metric)) not in (int,float) or not math.isfinite(v['metrics'][metric]) or v['metrics'][metric]<0 for v in per_variant.values()):
            return [],'waiting_for_data','',limitations+['primary metric unavailable or invalid']
        a = per_variant.get(control_key, {})
        a_val = (a.get("metrics") or {}).get(metric)
        if not a_val:
            return [], "inconclusive", "", limitations + [
                "zero_baseline: control metric is zero/missing — "
                "relative lift is undefined, not infinite"]
        comparisons = []
        winner, best = "", float("-inf")
        all_nonpositive = True
        for key, v in sorted(per_variant.items()):
            if key == control_key:
                continue
            val = (v.get("metrics") or {}).get(metric)
            if val is None:
                comparisons.append({"variant": key, "value": None,
                                    "lift": None, "coverage":
                                    v["coverage"]})
                continue
            lift = (val - a_val) / a_val
            gfail = self._guardrails(pol, v.get("metrics") or {})
            comparisons.append({
                "variant": key, "value": val, "lift": round(lift, 6),
                "guardrails": gfail or "ok",
                "coverage": v["coverage"],
                "snapshot_id": v.get("snapshot_id", "")})
            if lift > 0:
                all_nonpositive = False
            if not gfail and lift > best:
                best, winner = lift, key
        if winner and best > 0 and best >= pol["practical_lift"]:
            if pol["comparison_rule"] == "all":
                ok = all(c.get("lift") is not None and
                         c["lift"] >= pol["practical_lift"] and
                         c.get("guardrails") == "ok"
                         for c in comparisons)
                if not ok:
                    return comparisons, "inconclusive", "", \
                        limitations + [
                            "comparison_rule=all not met by every "
                            "treatment"]
            return comparisons, "provisional_winner", winner, \
                limitations
        if all_nonpositive:
            return comparisons, "no_improvement", "", limitations
        return comparisons, "inconclusive", "", limitations

    def _guardrails(self, pol, metrics):
        failures = []
        for name, floor in (pol.get("guardrails") or {}).items():
            v = metrics.get(name)
            if v is None:
                failures.append(f"{name}:missing")
            elif v < floor:
                failures.append(f"{name}:{v}<{floor}")
        return failures

    # ------------------------------------------------------ promote --

    def independent_experiments(self, template_ref):
        """Distinct SEEDS whose decided experiments won provisionally
        on this template — sibling variants count once."""
        seeds = set()
        for row in self._all("decision"):
            d = json.loads(row["body"])
            if d.get('conclusion')!='provisional_winner' or self._superseded(row['id']):continue
            er=self._record('experimentrevision','exp:'+d['experiment_id'])
            if er is None or er['revision']!=d['experiment_revision']:continue
            # A decision over old snapshots cannot remain independent evidence.
            pol=self.policy(d['experiment_id'],d['experiment_revision'])
            if not pol or pol['horizon']!=d['horizon']:continue
            current=self.decide(d['experiment_id'],d['experiment_revision'])
            if current['id']!=d['id'] or current['conclusion']!='provisional_winner':continue
            body = json.loads(er["body"])
            if body.get("template_ref") == template_ref and \
                    body.get("seed_id"):
                seeds.add(body["seed_id"])
        return seeds

    def promote(self, template_ref, *, min_independent=None, now=""):
        """Promote a reusable format only on INDEPENDENT experiments.
        Returns the promotion outcome with its limitation attached."""
        seeds = self.independent_experiments(template_ref)
        policies=[]
        for row in self._all('decisionpolicy'):
            p=json.loads(row['body']);er=self._record('experimentrevision','exp:'+p['experiment_id'])
            if er and json.loads(er['body']).get('template_ref')==template_ref:
                policies.append(p['promote_min_independent_experiments'])
        need=max([2,min_independent or 2,*policies])
        if len(seeds) >= need:
            status = "proven"
        elif seeds:
            status = "promising"
        else:
            status = "unproven"
        return {"template_ref": template_ref, "status": status,
                "independent_experiments": len(seeds),
                "seeds": sorted(seeds),
                "limitation": "one experiment's sibling variants are "
                              "not independent confirmations"}

    # --------------------------------------------------- hypotheses --

    def add_hypothesis(self, hypothesis_id, *, claim, evidence_ids=None,
                       uncertainty="medium", limitations=None,
                       status="candidate", source="", attributed_to="",
                       now=""):
        h = Hypothesis(schema_version="hypothesis.v1",
                       id=hypothesis_id, created_at=now or _now(),
                       claim=claim,
                       evidence_ids=list(evidence_ids or []),
                       uncertainty=uncertainty,
                       limitations=list(limitations or []),
                       status=status, source=source,
                       attributed_to=attributed_to)
        h.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(h)
        return h

    def hypotheses(self, query=""):
        out = []
        for row in self._all("hypothesis"):
            b = json.loads(row["body"])
            if not query or query.lower() in b["claim"].lower():
                out.append(b)
        return out

    def override_hypothesis(self, hypothesis_id, *, status, operator,
                            note="", now=""):
        """Operator override — attributed, never silent."""
        row = self._record("hypothesis", hypothesis_id)
        if row is None:
            raise ContractError("unknown_hypothesis", "id",
                                hypothesis_id)
        body = json.loads(row["body"])
        body.update(status=status, attributed_to=operator,
                    override_note=note)
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='hypothesis' "
                "AND id=? AND revision=?",
                (json.dumps(body), hypothesis_id, row["revision"]))
            u.events.append(f"hypothesis:{hypothesis_id}",
                            "operator_override",
                            {"operator": operator, "status": status})
        return body

    # ------------------------------------------------------ summary --

    def summary(self, decision_id):
        """Human-readable decision summary — always labelled
        observational; never uses causal language."""
        row = self._record("decision", decision_id)
        if row is None:
            raise ContractError("unknown_decision", "id", decision_id)
        d = json.loads(row["body"])
        lines = [
            f"Decision {decision_id} — experiment "
            f"{d['experiment_id']} r{d['experiment_revision']} @ "
            f"{d['horizon']}",
            f"Conclusion: {d['conclusion']}"
            + (f" (variant {d['winner']})" if d.get("winner") else ""),
            f"Policy {d['policy_version']} on "
            f"{d['primary_metric']}",
        ]
        for c in d["comparisons"]:
            lift = c.get("lift")
            lines.append(
                f"  {c['variant']}: {c.get('value')} vs control → "
                + (f"{lift:+.1%}" if lift is not None else "n/a")
                + (f" [{c['guardrails']}]"
                   if c.get("guardrails") not in (None, "ok") else ""))
        lines.append("Limitations:")
        for lim in d["limitations"]:
            lines.append(f"  - {lim}")
        return "\n".join(lines)

    # ---------------------------------------------------------- io --

    def _variants(self, experiment_id, revision):
        out = []
        for row in self._all("variantplan"):
            b = json.loads(row["body"])
            if b.get("experiment_id") == experiment_id and \
                    b.get("experiment_revision") == revision:
                out.append(b)
        return out

    def _publication_for(self,variant_plan_id):
        found=[json.loads(r['body']) for r in self._all('publication') if json.loads(r['body']).get('variant_plan_id')==variant_plan_id and json.loads(r['body']).get('status')=='public' and not json.loads(r['body']).get('deleted_at')]
        return found[0] if len(found)==1 else None

    def _snapshot(self,publication_id,horizon):
        rows=self.db.conn.execute("SELECT body FROM records WHERE kind='metricsnapshot' AND json_extract(body,'$.publication_id')=? AND json_extract(body,'$.horizon')=? ORDER BY json_extract(body,'$.observed_at') DESC,revision DESC",(publication_id,horizon)).fetchall()
        bodies=[json.loads(r['body']) for r in rows]
        return max(bodies,key=lambda b:(datetime.fromisoformat(b['observed_at'].replace('Z','+00:00')),b.get('revision',0))) if bodies else None

    def _decision_chain(self, base_id):
        """All decision records in the base_id chain, oldest first."""
        rows = [r for r in self._all("decision")
                if r["id"] == base_id or
                r["id"].startswith(f"{base_id}-v")]
        def number(r):
            suffix=r['id'][len(base_id):]
            return int(suffix[2:]) if suffix.startswith('-v') else 0
        return sorted(rows,key=number)

    def _record(self, kind, rid):
        return self.db.uow().records.get(kind, rid)

    def _all(self, kind):
        with self.db.uow() as u:
            return u.conn.execute(
                "SELECT * FROM records WHERE kind=? "
                "ORDER BY id, revision", (kind,)).fetchall()

    def _superseded(self,decision_id):
        row=self.db.conn.execute("SELECT value FROM meta WHERE key=?",('superseded:'+decision_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def _supersede(self,prior_row,new_id):
        # Supersession is a relation; the original decision bytes remain immutable.
        with self.db.uow() as u:
            u.conn.execute('INSERT INTO meta(key,value) VALUES(?,?)',('superseded:'+prior_row['id'],json.dumps(new_id)))
            u.events.append('decision:'+prior_row['id'],'superseded',{'by':new_id})
