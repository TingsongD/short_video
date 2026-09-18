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
from ..domain.records import (
    Decision, DecisionPolicy, Hypothesis, SeedSelection)


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
                      promote_min_independent_experiments=2,
                      seed_policy=None, now=""):
        """Bind the policy BEFORE any publication for the experiment."""
        now = now or _now()
        from ..analytics.service import (COMPLETE_DAYS, HORIZONS,
                                         NORMALIZED, PLATFORM_METRICS)
        horizons = set(HORIZONS) | set(COMPLETE_DAYS)
        if horizon not in horizons or primary_metric not in NORMALIZED or primary_metric=='public_views' or exposure_metric not in NORMALIZED or exposure_metric=='public_views' or comparison_rule not in ('any','all'):
            raise ContractError('invalid_decision_policy','metric/horizon/rule')
        if type(promote_min_independent_experiments) is not int or promote_min_independent_experiments<2:raise ContractError('invalid_promotion_threshold','threshold')
        if seed_policy:
            self._validate_seed_policy(seed_policy)
        er=self._record('experimentrevision','exp:'+experiment_id)
        if not er or er['revision']!=revision:raise ContractError('stale_revision','experiment')
        for pub in self._all("publication"):
            body = json.loads(pub["body"])
            vp = self._record("variantplan",
                              body.get("variant_plan_id", ""))
            # Only this revision's publications gate its policy — older
            # revisions' posts belong to older decision chains.
            if vp and json.loads(vp["body"]).get(
                    "experiment_id") == experiment_id and \
                    body.get("experiment_revision") == revision and \
                    body.get("status") not in ("failed", "cancelled"):
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
            seed_policy=dict(seed_policy or {}),
            status="frozen")
        pol.content_hash = _hash(
            experiment_id, revision,
            policy_version, primary_metric, horizon, exposure_metric,
            min_exposure, practical_lift, guardrails or {},
            comparison_rule,promote_min_independent_experiments,
            seed_policy or {})
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

    def _validate_seed_policy(self, sp):
        """§8.2/§9.3 freeze gate. A cross-platform policy must be
        completable: every required destination must have a qualified
        source for the window kinds the policy needs."""
        from ..analytics.service import (COMPLETE_DAYS, HORIZONS,
                                         PLATFORM_METRICS,
                                         WINDOW_SOURCES)
        from ..domain.records import PUBLISH_PLATFORMS
        import math
        mode = sp.get("mode", "weighted_rank")
        if mode not in ("primary_platform", "weighted_rank"):
            raise ContractError("invalid_seed_policy", "mode", mode)
        required = []
        if mode == "primary_platform":
            p = sp.get("primary_platform", "")
            if p not in PUBLISH_PLATFORMS:
                raise ContractError("invalid_seed_policy",
                                    "primary_platform", p)
            required = [p]
        else:
            weights = sp.get("weights") or {}
            if not weights or any(k not in PUBLISH_PLATFORMS
                                  for k in weights):
                raise ContractError("invalid_seed_policy", "weights",
                                    sorted(weights))
            if any(type(v) not in (int, float) or
                   not math.isfinite(v) or v <= 0
                   for v in weights.values()):
                raise ContractError("invalid_seed_policy", "weights",
                                    "non-positive")
            if abs(sum(weights.values()) - 1.0) > 1e-6:
                raise ContractError("invalid_seed_policy", "weights",
                                    "must sum to 1")
            required = sorted(weights)
        for p, cfg in (sp.get("per_platform") or {}).items():
            if p not in PUBLISH_PLATFORMS:
                raise ContractError("invalid_seed_policy",
                                    "per_platform", p)
            metric = (cfg or {}).get("primary_metric", "views")
            if metric not in PLATFORM_METRICS.get(p, {}):
                raise ContractError("invalid_seed_policy",
                                    f"per_platform.{p}.primary_metric",
                                    metric)
        rule = (sp.get("improvement_rule") or {})
        kind = rule.get("kind", "weighted_lift")
        if kind not in ("weighted_lift", "min_platforms"):
            raise ContractError("invalid_seed_policy",
                                "improvement_rule", kind)
        if kind == "min_platforms":
            k = rule.get("min_platforms", 0)
            if type(k) is not int or k < 1 or k > len(required):
                raise ContractError("invalid_seed_policy",
                                    "improvement_rule.min_platforms", k)
        mm = sp.get("min_margin", 0)
        if type(mm) not in (int, float) or not math.isfinite(mm) or mm < 0:
            raise ContractError("invalid_seed_policy", "min_margin")
        for opt in ("max_late_hours", "max_upstream_age_hours",
                    "denominator_floor"):
            v = (rule if opt == "denominator_floor" else sp).get(opt)
            if v is not None and (type(v) not in (int, float) or
                                  not math.isfinite(v) or v < 0):
                raise ContractError("invalid_seed_policy", opt, v)
        named = rule.get("platforms")
        if named is not None and (
                not isinstance(named, list) or
                any(p not in required for p in named)):
            raise ContractError("invalid_seed_policy",
                                "improvement_rule.platforms", named)
        # §8.2 capability gate: every required platform needs a
        # qualified source for each window kind the policy consumes.
        for hkey in ("provisional_horizon", "mature_horizon"):
            h = sp.get(hkey, "")
            if not h:
                continue
            if h not in HORIZONS and h not in COMPLETE_DAYS:
                raise ContractError("invalid_seed_policy", hkey, h)
            kind_needed = ("source_calendar_window"
                           if h in COMPLETE_DAYS
                           else "observed_lifetime_at_age")
            missing = [p for p in required
                       if not WINDOW_SOURCES.get(p, {}).get(kind_needed)]
            if missing:
                raise ContractError(
                    "window_capability_missing", hkey,
                    f"{h}:{kind_needed} unavailable on "
                    f"{','.join(missing)}")

    # ------------------------------------------------------- decide --

    def decide(self, experiment_id, revision, horizon="", platform="",
               now="", account=""):
        """Compute the decision deterministically from stored
        evidence. Identical inputs → identical record (idempotent);
        changed inputs → a new decision revision. With `platform` the
        decision is control-relative on ONE destination lane; the
        record id gains the platform suffix (PL-05). `account`
        narrows the slot to one account on that platform."""
        now = now or _now()
        pol = self.policy(experiment_id, revision)
        if pol is None:
            raise ContractError("policy_not_frozen", "experiment_id",
                                experiment_id)
        if horizon and horizon!=pol['horizon']:raise ContractError('frozen_horizon','horizon')
        horizon = pol['horizon']
        variants = self._variants(experiment_id, revision)
        if {v['variant_key'] for v in variants}!=set('ABCD'):
            raise ContractError("no_variants", "experiment_id",
                                experiment_id)
        control_key = "A"
        per_variant = self._evidence(variants, horizon, platform,
                                     account)
        evidence = [v["snapshot_id"] for v in per_variant.values()
                    if v.get("snapshot_id")]

        post_ids=[(v.get('post_id'),v.get('publication_id')) for v in per_variant.values()]
        if len({x[0] for x in post_ids if x[0]})!=len(per_variant):
            for v in per_variant.values():v['coverage']='missing_or_duplicate_post'
        comparisons, conclusion, winner, limitations = \
            self._evaluate(pol, per_variant, control_key)
        kinds={v.get('window',{}).get('kind') for v in per_variant.values() if v.get('window')}
        if kinds=={'source_calendar'}:
            limitations=limitations+['source_calendar window — the source days cover the age but are not an exact elapsed rolling window']
        inputs_hash = _hash(
            pol["content_hash"], horizon, platform, account,
            {k: {"snap": v.get("snapshot_id", ""),
                 "cov": v["coverage"],
                 "m": v.get("metrics", {}),"window":v.get("window"),"snapshot_revision":v.get("snapshot_revision"),"post_id":v.get("post_id")}
             for k, v in sorted(per_variant.items())})
        did = f"dec-{experiment_id}-r{revision}-{horizon}"
        if platform:did = f"{did}-{platform}"
        if account:did = f"{did}-{account}"
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
            platform=platform,
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
                # Derived rounds share one creative lineage — count by
                # independence group, never by raw derived seed id.
                seed_row = self._record("seed", body["seed_id"])
                sb = (json.loads(seed_row["body"])
                      if seed_row else {})
                seeds.add(sb.get("independence_group") or
                          sb.get("lineage_root_id") or
                          body["seed_id"])
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

    # -------------------------------------------------- select_seed --

    def _seed_platforms(self, sp, pol):
        """Required destination lanes from the frozen seed policy."""
        mode = sp.get("mode", "weighted_rank")
        if mode == "primary_platform":
            return [sp["primary_platform"]]
        return sorted((sp.get("weights") or {}).keys())

    def _seed_weights(self, sp, required):
        if sp.get("mode", "weighted_rank") == "primary_platform":
            return {required[0]: 1.0}
        return dict(sp.get("weights") or {})

    def _platform_eval(self, pol, platform, sp, per_variant):
        """§9.3 step 1 — per-platform validity for one lane. A
        declared per-platform primary-metric override replaces the
        global metric on that lane (§8.3 capability matrix)."""
        import math
        metric = ((sp.get("per_platform") or {}).get(platform) or {}
                  ).get("primary_metric") or pol["primary_metric"]
        exp = pol["exposure_metric"]
        missing = [k for k, v in per_variant.items()
                   if v["coverage"] != "complete"]
        if missing:
            return {"status": "waiting", "missing": sorted(missing),
                    "table": {}}
        a = per_variant["A"]
        a_g = self._guardrails(pol, a.get("metrics") or {})
        if a_g:
            return {"status": "invalid_comparison",
                    "reason": f"unsafe control: {a_g}", "table": {}}
        a_exp = (a.get("metrics") or {}).get(exp)
        if type(a_exp) not in (int, float) or \
                not math.isfinite(a_exp) or \
                a_exp < pol["min_exposure"]:
            return {"status": "insufficient_exposure",
                    "detail": f"control {exp}={a_exp}", "table": {}}
        a_val = (a.get("metrics") or {}).get(metric)
        if not a_val:
            return {"status": "invalid_comparison",
                    "reason": "zero_baseline", "table": {}}
        table = {}
        for key, v in per_variant.items():
            m = v.get("metrics") or {}
            val = m.get(metric)
            e = m.get(exp)
            table[key] = {
                "value": val, "exposure": e, "lift": None,
                "guardrails": self._guardrails(pol, m) or "ok",
                "coverage": v["coverage"],
                "exposure_ok": type(e) in (int, float) and
                math.isfinite(e) and e >= pol["min_exposure"]}
            if key != "A" and type(val) in (int, float) and \
                    math.isfinite(val):
                table[key]["lift"] = round((val - a_val) / a_val, 6)
        return {"status": "ok", "table": table}

    def select_seed(self, experiment_id, revision, horizon="", now="",
                    account="", accounts=None):
        """Best-of-four seed evaluation at one checkpoint (§9.3).

        Evaluation order is fixed: per-platform validity → global
        eligibility → ranks → weighted score → score-order candidate
        evaluation → explicit outcome. A is a legal winner; evaluation
        is versioned by horizon + inputs hash and is separate from
        child creation."""
        now = now or _now()
        pol = self.policy(experiment_id, revision)
        if pol is None:
            raise ContractError("policy_not_frozen", "experiment_id",
                                experiment_id)
        sp = pol.get("seed_policy") or {}
        horizon = horizon or sp.get("provisional_horizon") or \
            pol["horizon"]
        required = self._seed_platforms(sp, pol) or [pol.get(
            "seed_policy", {}).get("primary_platform", "youtube")]
        variants = self._variants(experiment_id, revision)
        if {v['variant_key'] for v in variants} != set('ABCD'):
            raise ContractError("no_variants", "experiment_id",
                                experiment_id)

        accounts = dict(accounts or {})
        if account:
            accounts = {p: account for p in required}
        max_late = sp.get("max_late_hours")
        max_upstream = sp.get("max_upstream_age_hours")
        per_platform, evidence, decision_ids = {}, [], []
        for platform in required:
            acct = accounts.get(platform) or None
            pv = self._evidence(variants, horizon, platform, acct or "",
                                max_late=max_late,
                                max_upstream=max_upstream)
            per_platform[platform] = self._platform_eval(
                pol, platform, sp, pv)
            if per_platform[platform]["status"] == "ok":
                did = f"dec-{experiment_id}-r{revision}-{horizon}-" \
                      f"{platform}" + (f"-{acct}" if acct else "")
                decision_ids.append(did)
            for v in pv.values():
                if v.get("snapshot_id"):
                    evidence.append(v["snapshot_id"])

        outcome, winner, basis = self._evaluate_seed(
            pol, sp, per_platform, required)
        basis["evidence_ids"] = list(evidence)

        inputs_hash = _hash(
            pol["content_hash"], horizon, required, dict(accounts),
            {p: {"status": e["status"],
                 "table": {k: {"v": t.get("value"), "l": t.get("lift"),
                               "g": t.get("guardrails"),
                               "x": t.get("exposure_ok")}
                           for k, t in sorted(
                               (e.get("table") or {}).items())}}
             for p, e in sorted(per_platform.items())},
            sorted(evidence))

        sid = f"sel-{experiment_id}-r{revision}-{horizon}"
        priors = self._selection_chain(sid)
        latest = priors[-1] if priors else None
        if latest and json.loads(latest["body"]).get(
                "inputs_hash") == inputs_hash:
            body = json.loads(latest["body"])
            body["_idempotent"] = True
            return body
        if latest:
            self._supersede_selection(latest)
            sid = f"{sid}-v{len(priors)}"

        status = {"waiting": "waiting",
                  "inconclusive": "inconclusive"}.get(
            outcome, "confirmed" if horizon == sp.get(
                "mature_horizon") else "provisional")
        sel = SeedSelection(
            schema_version="seed_selection.v1", id=sid,
            created_at=now, experiment_id=experiment_id,
            experiment_revision=revision, horizon=horizon,
            status=status, winner_variant=winner, basis=basis,
            decision_ids=decision_ids,
            inputs_hash=inputs_hash,
            limitations=[LIMIT_OBSERVATIONAL, LIMIT_SIBLINGS])
        sel.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(sel)
            u.events.append(f"experiment:{experiment_id}",
                            "seed_evaluated",
                            {"selection": sid, "outcome": outcome,
                             "winner": winner})
        return {**sel.to_dict(), "outcome": outcome,
                "per_platform": per_platform}

    def _evaluate_seed(self, pol, sp, per_platform, required):
        """§9.3 steps 2-6. Returns (outcome, winner_variant, basis)."""
        import math
        waiting = [p for p, e in per_platform.items()
                   if e["status"] == "waiting"]
        invalid = [p for p, e in per_platform.items()
                   if e["status"] in ("invalid_comparison",
                                      "insufficient_exposure")]
        basis = {"per_platform": per_platform, "required": required,
                 "weights": self._seed_weights(sp, required)}
        if waiting:
            return "waiting", "", {**basis, "missing": waiting}
        if invalid:
            # Unsafe control OR inadequate control exposure on a
            # required lane — a lift can never be computed against it.
            return "inconclusive", "", {**basis,
                                        "invalid_comparison": invalid}

        # Step 2 — eligibility (§9.3): a variant is eligible iff it
        # passes exposure AND guardrails on every required platform
        # that produced a valid comparison. Failing either on any
        # required lane disqualifies it globally.
        eligible, disqualified = {}, {}
        for p, e in per_platform.items():
            for key, t in e["table"].items():
                why = []
                if t["guardrails"] != "ok":
                    why.append(f"guardrails:{t['guardrails']}")
                if not t["exposure_ok"]:
                    why.append("exposure")
                if why:
                    eligible[key] = False
                    disqualified.setdefault(key, []).append(
                        f"{p}:{','.join(why)}")
                else:
                    eligible.setdefault(key, True)
        basis["disqualified"] = disqualified

        # Step 3 — per-platform ranks by the frozen primary metric,
        # highest is rank 1, average ranks for exact ties. Ineligible
        # variants still receive ranks — the rank is evidence.
        ranks = {}
        for p, e in per_platform.items():
            def val(item):
                v = item[1]["value"]
                return (v if type(v) in (int, float) and
                        math.isfinite(v) else float("-inf"))
            ordered = sorted(e["table"].items(),
                             key=lambda kv: (-val(kv), kv[0]))
            i = 0
            while i < len(ordered):
                j = i
                while j + 1 < len(ordered) and \
                        val(ordered[j + 1]) == val(ordered[i]):
                    j += 1
                avg = (i + j + 2) / 2.0     # mean of positions i+1..j+1
                for n in range(i, j + 1):
                    ranks.setdefault(ordered[n][0], {})[p] = avg
                i = j + 1

        # Step 4 — aggregate score: 100×(4−rank)/3 per platform, then
        # the weighted mean with frozen weights.
        weights = basis["weights"]
        scores = {k: 0.0 for k in "ABCD"}
        for p in per_platform:
            for k, pr in ranks.items():
                if p in pr:
                    scores[k] += (weights.get(p, 0) *
                                  100 * (4 - pr[p]) / 3)
        basis["ranks"], basis["scores"] = ranks, scores

        # Step 5 — eligible variants in score order. A challenger passes
        # iff (a) it leads the next eligible contender by ≥ min_margin
        # and (b) it satisfies the improvement_rule against A. If the
        # top scorer fails, evaluate the next eligible scorer.
        order = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        if len(order) > 1 and math.isclose(
                order[0][1], order[1][1], rel_tol=0, abs_tol=1e-9):
            return "inconclusive", "", {**basis, "tie": [
                order[0][0], order[1][0]]}
        rule = sp.get("improvement_rule") or {}
        margin = sp.get("min_margin", 0)
        for i, (key, score) in enumerate(order):
            if not eligible.get(key, True):
                continue
            nxt = next((s for k2, s in order[i + 1:]
                        if eligible.get(k2, True)), 0.0)
            lead = round(score - nxt, 6)
            basis.setdefault("evaluated", {}).setdefault(
                key, {})["margin"] = lead
            if key == "A":
                return "retain_control", "A", basis
            if lead < margin:
                basis["evaluated"][key]["margin_fail"] = {
                    "lead": lead, "required": margin}
                continue
            passed, why = self._improvement(
                pol, rule, per_platform, key, weights, required)
            basis["evaluated"][key].update(why)
            if passed:
                return "champion", key, basis
        if eligible.get("A", True):
            return "retain_control", "A", basis
        return "inconclusive", "", basis

    def _improvement(self, pol, rule, per_platform, cand, weights,
                     required):
        """Declared improvement rule (§9.3 step 5b).
        weighted_lift: Σ_p weight_p × relative lift_p ≥ practical_lift —
        relative lift uses the declared denominator floor so a weak
        baseline never yields infinity.
        min_platforms: relative lift ≥ practical_lift on ≥ K named
        required platforms."""
        import math
        lift_req = pol["practical_lift"]
        kind = rule.get("kind", "weighted_lift")
        floor = rule.get("denominator_floor", 1e-9)

        def rel_lift(p):
            t = per_platform[p]["table"]
            cv, av = t[cand].get("value"), t["A"].get("value")
            if type(cv) not in (int, float) or not math.isfinite(cv) or \
                    type(av) not in (int, float) or \
                    not math.isfinite(av):
                return None
            return (cv - av) / max(av, floor)

        if kind == "min_platforms":
            named = rule.get("platforms") or required
            need = rule.get("min_platforms", 1)
            beaten = [p for p in named
                      if p in per_platform
                      and rel_lift(p) is not None
                      and rel_lift(p) >= lift_req
                      and per_platform[p]["table"][cand]["exposure_ok"]]
            return len(beaten) >= need, {
                "rule": "min_platforms", "beaten": beaten,
                "need": need}
        parts, total = {}, 0.0
        for p in required:
            rl = rel_lift(p)
            if rl is None:
                return False, {"rule": "weighted_lift",
                               "detail": f"primary metric unknown on {p}"}
            parts[p] = round(rl, 6)
            total += weights.get(p, 0) * rl
        return total >= lift_req, {"rule": "weighted_lift",
                                   "weighted_lift": round(total, 6),
                                   "required": lift_req,
                                   "relative_lifts": parts}

    def _selection_chain(self, base_id):
        rows = [r for r in self._all("seedselection")
                if r["id"] == base_id or
                r["id"].startswith(f"{base_id}-v")]
        def number(r):
            suffix = r['id'][len(base_id):]
            return int(suffix[2:]) if suffix.startswith('-v') else 0
        return sorted(rows, key=number)

    def _supersede_selection(self, prior_row):
        with self.db.uow() as u:
            u.conn.execute(
                'INSERT INTO meta(key,value) VALUES(?,?)',
                ('superseded:' + prior_row['id'],
                 json.dumps({"kind": "seedselection"})))
            u.events.append('selection:' + prior_row['id'],
                            'superseded', {})
            # A child round built on this selection's basis is marked
            # superseded — history kept, basis honestly invalidated
            # (§9.3 mature reevaluation). Nothing is deleted.
            for r in u.conn.execute(
                    "SELECT body FROM records WHERE kind='roundlineage'"
                    " AND json_extract(body,'$.parent_selection_id')=?",
                    (prior_row['id'],)).fetchall():
                c = json.loads(r[0])
                if c.get('status') in ('proposed', 'active'):
                    c['status'] = 'superseded'
                    u.conn.execute(
                        "UPDATE records SET body=?,updated_at=? WHERE"
                        " kind='roundlineage' AND id=?",
                        (json.dumps(c), _now(), c['id']))
                    u.events.append(
                        'lineage:' + c['id'], 'basis_superseded',
                        {'selection': prior_row['id']})

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

    def _publication_for(self,variant,platform=None,account=None):
        """Exactly one public publication for the destination slot —
        (variant, platform, account). A second account on the same
        platform resolves only when the caller names it (PL-05)."""
        found=[json.loads(r['body']) for r in self._all('publication')
            if json.loads(r['body']).get('variant_plan_id')==variant['id']
            and json.loads(r['body']).get('experiment_revision')==variant.get('experiment_revision')
            and json.loads(r['body']).get('status')=='public'
            and not json.loads(r['body']).get('deleted_at')]
        if platform:
            found=[p for p in found if p.get('platform')==platform]
        if account:
            found=[p for p in found if p.get('account_id')==account]
        return found[0] if len(found)==1 else None

    def _window_expect(self, platform, horizon):
        """(accepted window kinds, hours) a usable snapshot may carry
        for this lane. YouTube elapsed horizons accept an exact rolling
        window OR the source-calendar days covering the same age — the
        kind is recorded on the snapshot either way (PL-04)."""
        from ..analytics.service import COMPLETE_DAYS, HORIZONS
        if horizon in COMPLETE_DAYS:
            return {'source_calendar_window'}, COMPLETE_DAYS[horizon] * 24
        if platform and platform != 'youtube':
            return {'observed_lifetime_at_age'}, HORIZONS[horizon]
        return {'exact_rolling', 'source_calendar'}, HORIZONS[horizon]

    def _evidence(self, variants, horizon, platform, account="",
                  max_late=None, max_upstream=None):
        """Per-variant evidence table for one destination slot."""
        want_kinds, want_hours = self._window_expect(platform, horizon)
        per_variant = {}
        for vp in variants:
            pub = self._publication_for(vp, platform or None,
                                        account or None)
            snap = self._snapshot(pub["id"], horizon, want_kinds,
                                  want_hours, max_late=max_late,
                                  max_upstream=max_upstream) \
                if pub else None
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
                entry['window']['observed_at']=snap.get('observed_at')
                entry['window']['late']=snap.get(
                    'actual_coverage',{}).get('late')
                if entry['window']['kind'] not in want_kinds or entry['window']['hours']!=want_hours:
                    entry['coverage']='incompatible_window'
            per_variant[vp["variant_key"]] = entry
        return per_variant

    def _snapshot(self,publication_id,horizon,kinds=None,hours=None,
                  max_late=None,max_upstream=None):
        """Best eligible snapshot for (pub, horizon): prefer a window
        the policy accepts and better completeness over a merely later
        retry — an unobserved-later attempt must not mask usable
        evidence. When the policy declares freshness bounds, stale
        evidence is excluded rather than merely labeled: max_late caps
        observed_at − due_at hours, max_upstream caps observed_at −
        upstream_freshness hours (absent freshness data fails a
        declared upstream bound — it cannot be verified)."""
        rows=self.db.conn.execute("SELECT body FROM records WHERE kind='metricsnapshot' AND json_extract(body,'$.publication_id')=? AND json_extract(body,'$.horizon')=? ORDER BY json_extract(body,'$.observed_at') DESC,revision DESC",(publication_id,horizon)).fetchall()
        bodies=[json.loads(r['body']) for r in rows]
        bodies=[b for b in bodies if self._fresh(
            b,max_late,max_upstream)]
        if not bodies:return None
        rank={'complete':3,'partial':2,'pending':1,'failed':0}
        def score(b):
            rp=b.get('requested_period') or {}
            kind_ok=(kinds is None or rp.get('window_kind') in kinds)
            hours_ok=(hours is None or rp.get('horizon_hours')==hours)
            return (kind_ok and hours_ok,rank.get(b.get('completeness'),0),
                    datetime.fromisoformat(b['observed_at'].replace('Z','+00:00')),b.get('revision',0))
        return max(bodies,key=score)

    def _fresh(self, snap, max_late, max_upstream):
        """Freshness rules. Unconditional: a lifetime-at-age
        observation recorded as 'late' measured a different age than
        the horizon declares — it is evidence for a different horizon,
        never merely 'late'. Declared policy bounds (max_late,
        max_upstream) then apply on top; missing data needed to verify
        a declared bound fails closed."""
        rp = snap.get('requested_period') or {}
        if rp.get('window_kind') == 'observed_lifetime_at_age' and \
                (snap.get('actual_coverage') or {}).get('late'):
            return False
        obs = snap.get('observed_at')
        if not obs:
            return not (max_late or max_upstream)
        observed = datetime.fromisoformat(obs.replace('Z', '+00:00'))
        if max_late is not None:
            due = rp.get('due_at')
            if not due:
                return False
            late_h = (observed - datetime.fromisoformat(
                due.replace('Z', '+00:00'))).total_seconds() / 3600
            if late_h > max_late:
                return False
        if max_upstream is not None:
            up = rp.get('upstream_freshness')
            if not up:
                return False
            up_h = (observed - datetime.fromisoformat(
                up.replace('Z', '+00:00'))).total_seconds() / 3600
            if up_h > max_upstream:
                return False
        return True

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
