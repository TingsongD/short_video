"""Discovery scans (F10 checklist 5–6): preflighted, paginated research
calls through the executor; per-(query,page) caching; partial coverage
recorded explicitly when credits run out; ranked, explainable
candidates exported to the seed registry.

Selection never authorizes generation — exporting a seed only makes it
available for acquisition planning.
"""
import json

from ..domain.errors import ContractError
from ..domain.records import DiscoveryRun
from ..seeds.registry import SeedRegistry
from ..store.uow import utcnow
from ..testing.fakes import ProviderError
from .cohort import build_cohort
from .evaluate import evaluate


class DiscoveryService:
    def __init__(self, db, registry, executor, provider,
                 provider_name="viral_outliers", cache_ttl_s=86400):
        self.db = db
        self.registry = registry
        self.executor = executor
        self.provider = provider
        self.provider_name = provider_name
        self.cache_ttl_s = cache_ttl_s

    # ------------------------------------------------------------- scan

    def scan(self, queries, pages=1, page_size=20, mode="either",
             baseline_threshold=5.0, follower_threshold=2.0,
             run_id=None, export_selected=True, max_calls=None):
        if not queries:
            raise ContractError("empty_scan", "queries")
        run_id = run_id or f"drun-{utcnow()}"
        planned = [(q, p) for q in queries for p in range(1, pages + 1)]
        received, per_query, pool = [], {}, []
        partial = None
        for query, page in planned:
            rows = self._page(query, page, page_size, run_id,
                              planned, received, max_calls)
            if rows is None:                      # credits exhausted
                partial = f"insufficient_credits at {query!r} page {page}"
                break
            received.append((query, page))
            per_query.setdefault(query, []).append(page)
            pool.extend(rows)
        run = self._finish(run_id, queries, pages, page_size, mode,
                           baseline_threshold, follower_threshold,
                           planned, received, per_query, pool, partial,
                           export_selected)
        return run

    # ------------------------------------------------------------ pages

    def _page(self, query, page, page_size, run_id, planned, received,
              max_calls):
        key = f"{query}|{page}"
        cached = self.db.conn.execute(
            "SELECT body, observed_at FROM discovery_cache WHERE "
            "query_key=? AND page=?", (key, page)).fetchone()
        if cached and self._fresh(cached["observed_at"]):
            return json.loads(cached["body"])
        if max_calls is not None and len(received) >= max_calls:
            return None
        request = {"kind": "search", "query": query, "page": page,
                   "page_size": page_size, "run_id": run_id}
        aid = self.executor.prepare(
            f"job-discovery-{run_id}", len(received) + 1, request,
            kind="discovery_search", route=f"{self.provider_name}:search")
        try:
            op = self.executor.submit(
                aid, call=lambda: self.provider.submit(request))
        except ProviderError as e:
            if e.code == "insufficient_credits":
                return None
            raise
        if op.get("status") == "accepted":
            op = self.executor.poll(aid)
        posts = (op.get("result") or {}).get("posts", [])
        with self.db.uow() as u:
            u.conn.execute(
                "INSERT OR REPLACE INTO discovery_cache(query_key,page,"
                "body,observed_at,run_id) VALUES(?,?,?,?,?)",
                (key, page, json.dumps(posts), utcnow(), run_id))
        return posts

    def _fresh(self, observed_at):
        from datetime import datetime, timezone
        age = (datetime.now(timezone.utc)
               - datetime.fromisoformat(
                   observed_at.replace("Z", "+00:00"))).total_seconds()
        return age < self.cache_ttl_s

    # ----------------------------------------------------------- finish

    def _finish(self, run_id, queries, pages, page_size, mode,
                baseline_threshold, follower_threshold, planned,
                received, per_query, pool, partial, export_selected):
        # Dedupe by post identity; first observation wins.
        seen, candidates = set(), []
        for row in pool:
            pid = row.get("post_id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            candidates.append(row)
        results = []
        cohorts = {}
        for c in candidates:
            cohort = build_cohort(c, candidates)
            cohorts[c["post_id"]] = cohort
            results.append(evaluate(
                c, cohort, mode=mode,
                follower_threshold=follower_threshold,
                baseline_threshold=baseline_threshold))
        results.sort(key=lambda r: (
            not r["selected"],
            -(r["baseline_multiple"] or r["follower_multiple"] or 0)))
        exported = []
        if export_selected:
            for r in results:
                if not r["selected"]:
                    continue
                cand = next(c for c in candidates
                            if c["post_id"] == r["post_id"])
                url = cand.get("source_url")
                if not url:
                    continue
                try:
                    seed, _ = self.registry.submit_url(
                        url, via="discovery",
                        observed_at=cand.get("observed_at") or utcnow())
                    exported.append(seed.id)
                except ContractError:
                    pass               # unusable URL stays unexported
        run = DiscoveryRun(
            schema_version="discovery_run.v1",
            id=run_id, created_at=utcnow(),
            plan={"queries": queries, "pages": pages,
                  "page_size": page_size, "selection_mode": mode,
                  "baseline_threshold": baseline_threshold,
                  "follower_threshold": follower_threshold},
            status="partial" if partial else "complete",
            coverage={"planned_pages": len(planned),
                      "received_pages": len(received),
                      "per_query": {q: sorted(p) for q, p in
                                    per_query.items()},
                      "partial_reason": partial},
            candidates=results,
            cohort={pid: {"size": c["size"],
                          "mean_views": c["mean_views"],
                          "median_views": c["median_views"],
                          "included": c["included"],
                          "excluded": c["excluded"],
                          "flags": c["flags"]}
                    for pid, c in cohorts.items()},
            exported_seed_ids=exported)
        run.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(run)
            u.events.append(f"discovery:{run_id}", "run_finished",
                            {"status": run.status,
                             "candidates": len(results),
                             "exported": len(exported)})
        return run
