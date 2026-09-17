"""Discovery scans (F10 checklist 5–6): preflighted, paginated research
calls through the executor; per-(query,page) caching; partial coverage
recorded explicitly when credits run out; ranked, explainable
candidates exported to the seed registry.

Selection never authorizes generation — exporting a seed only makes it
available for acquisition planning.
"""
import json

from ..domain.errors import ContractError
from ..domain.records import DiscoveryRun, content_hash
from ..seeds.registry import SeedRegistry
from ..store.uow import utcnow
from ..testing.fakes import ProviderError
from .cohort import build_cohort
from .evaluate import evaluate


class DiscoveryService:
    def __init__(self, db, registry, executor, provider,
                 provider_name="viral_outliers", cache_ttl_s=86400, effects=None, account='', settings=None):
        self.db = db
        self.effects = effects
        self.registry = registry
        self.executor = executor
        self.provider = provider
        self.provider_name = provider_name
        self.cache_ttl_s = cache_ttl_s
        self.account=account or getattr(provider,'account','')
        self.settings=dict(settings or {})
        self._calls=0

    # ------------------------------------------------------------- scan

    def scan(self, queries, pages=1, page_size=20, mode="either",
             baseline_threshold=5.0, follower_threshold=2.0,
             run_id=None, export_selected=True, max_calls=None):
        if not queries:
            raise ContractError("empty_scan", "queries")
        if not 1<=pages<=10 or not 1<=page_size<=100:raise ContractError('invalid_scan_bounds','pages/page_size')
        self._calls=0
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
                           export_selected,max_calls)
        return run

    # ------------------------------------------------------------ pages

    def _page(self, query, page, page_size, run_id, planned, received,
              max_calls):
        request = {"kind": "search", "query": query, "page": page,
                   "page_size": page_size, **self.settings}
        return self._request(request,run_id,max_calls)

    def _request(self,request,run_id,max_calls):
        key=content_hash({'provider':self.provider_name,'account':self.account,'request':request,'query_version':'creator-history.v2'})
        page=request['page']
        cached = self.db.conn.execute(
            "SELECT body, observed_at FROM discovery_cache WHERE "
            "query_key=? AND page=?", (key, page)).fetchone()
        if cached and self._fresh(cached["observed_at"]):
            return json.loads(cached["body"])
        if max_calls is not None and self._calls >= max_calls:
            return None
        request={**request,'run_id':run_id}
        if self.effects is None:
            raise ContractError("authority_required", "research")
        aid = self.effects(request, f"job-discovery-{run_id}", "research", self.provider_name, "search")
        self.executor.require_request(aid, request)
        self.executor.provider=self.provider
        try:
            self._calls+=1
            op = self.executor.submit(
                aid, call=lambda: self.provider.submit(request))
        except ProviderError as e:
            if e.code == "insufficient_credits":
                return None
            raise
        if op.get('reused') or op.get("status") in ('accepted','running'):
            op = self.executor.poll(aid)
        if op.get('status')!='succeeded':raise ContractError('research_unfinished','attempt_id',aid)
        posts = (op.get("result") or {}).get("posts", [])
        if not isinstance(posts,list) or any(not isinstance(p,dict) for p in posts):raise ContractError('research_response_invalid','posts')
        if type(op.get('actual_credits')) is int:
            from ..execution.effects import EffectService
            EffectService(self.db,self.executor).settle(aid,op['actual_credits'],'reported_usage',op['operation_id'])
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
        return 0<=age < self.cache_ttl_s

    # ----------------------------------------------------------- finish

    def _finish(self, run_id, queries, pages, page_size, mode,
                baseline_threshold, follower_threshold, planned,
                received, per_query, pool, partial, export_selected,max_calls=None,history_by_creator=None):
        existing=self.db.uow().records.get('discoveryrun',run_id)
        if existing:return DiscoveryRun(**json.loads(existing['body']))
        # Dedupe by platform and post identity; first observation wins.
        seen, candidates = set(), []
        for row in pool:
            pid = (row.get('platform'),row.get("post_id"))
            if not pid[1] or pid in seen:
                continue
            seen.add(pid)
            candidates.append(row)
        results = []
        cohorts = {}
        histories=dict(history_by_creator or {});history_status={}
        for c in candidates:
            scope=(c.get('platform'),c.get('creator_id'))
            if scope not in histories:
                histories[scope]=[]
                if c.get('handle') and all(scope):
                    request={**self.settings,'kind':'creator_history','query':'','handle':c['handle'],
                        'platforms':[c['platform']],'page':1,'page_size':100,'time_frame':'all_time','sort_by':'date_desc'}
                    try:
                        fetched=self._request(request,run_id,max_calls)
                        histories[scope]=fetched or []
                        history_status[str(scope)]='received' if fetched is not None else 'budget_exhausted'
                    except ContractError as error:
                        if error.code not in ('operation_not_authorized','authority_required','budget_exceeded','research_unfinished'):raise
                        history_status[str(scope)]=error.code
                else:history_status[str(scope)]='creator_lookup_unavailable'
            cohort = build_cohort(c, histories[scope],now=utcnow())
            cohorts[c['platform']+':'+c["post_id"]] = cohort
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
                            if (c.get('platform'),c["post_id"]) == (r.get('platform'),r["post_id"]))
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
            cohort=cohorts,
            exported_seed_ids=exported)
        run.validate_or_raise()
        run.coverage.update(creator_history=history_status,actual_calls=self._calls)
        with self.db.uow() as u:
            u.records.put(run)
            u.events.append(f"discovery:{run_id}", "run_finished",
                            {"status": run.status,
                             "candidates": len(results),
                             "exported": len(exported)})
        return run
