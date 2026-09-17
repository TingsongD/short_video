"""Unique-work asset graph (F21): takes → provider-duration
allocations → dedupe by canonical request → DAG of
picture/download/review/compose/deliver nodes.

Pure functions: no I/O, no provider calls, no clock.
"""
import json
import hashlib


def canonical_request_key(request):
    """Dedupe identity: prompt + settings + ref hashes + audio hash.
    Two takes producing the same canonical request share ONE work item
    and ONE charge."""
    return hashlib.sha256(json.dumps(
        request, sort_keys=True, separators=(",", ":"))
        .encode()).hexdigest()[:16]


def expand_take(duration_s, supported, handle_s=0.0):
    """Fit a required duration into provider-supported durations.
    → {"allocations":[{duration_s,offset_s,split}], "status":"ok"}
      or {"status":"needs_manual","reason":...}
    Never stretches or under-covers silently: a take over the max
    supported duration splits into supported chunks with declared
    boundaries; an unrepresentable remainder needs manual coverage."""
    if duration_s <= 0 or handle_s < 0:
        return {"status": "needs_manual", "reason": "invalid_duration", "allocations": []}
    need = duration_s + handle_s
    supported = sorted((d for d in supported if d > 0), reverse=True)
    if not supported:
        return {"status": "needs_manual", "reason": "no_durations",
                "allocations": []}
    cover = [d for d in supported if d >= need]
    if cover:
        # smallest supported duration that covers the take
        alloc = min(cover)
        return {"status": "ok",
                "allocations": [{"duration_s": alloc, "offset_s": 0.0,
                                 "split": False,
                                 "covers_s": need,
                                 "over_s": round(alloc - need, 3)}]}
    # split greedily into largest supported chunks
    allocs, remaining, off = [], need, 0.0
    while remaining > 0:
        chunk = min((d for d in supported if d >= remaining), default=max(supported))
        allocs.append({"duration_s": chunk, "offset_s": off,
                       "split": True, "covers_s": min(chunk, remaining),
                       "over_s": round(max(0, chunk - remaining), 6)})
        off += chunk
        remaining = max(0, round(remaining - chunk, 6))
    return {"status": "ok", "allocations": allocs,
            "split_reason": f"{duration_s}s exceeds max supported "
                            f"{supported[0]}s — declared split"}


def build_graph(plan_id, takes, provider, model, durations):
    """takes: [{variant,slot,duration_s,request}].
    → {"nodes": {node_key: node}, "stats": {...}}
    Node kinds: picture (unique per request), download (per picture),
    review/compose/deliver (per consuming variant)."""
    nodes, by_req = {}, {}
    stats = {"takes": len(takes), "unique_pictures": 0,
             "shared_pictures": 0, "splits": 0, "manual_needed": 0}
    for t in takes:
        key = canonical_request_key({"request": t["request"], "provider": provider,
                                     "model": model, "duration_s": t["duration_s"],
                                     "handle_s": t.get("handle_s", 0)})
        pkey = f"pic:{key}"
        if pkey not in nodes:
            fit = expand_take(t["duration_s"], durations,
                              t.get("handle_s", 0.0))
            if fit["status"] == "needs_manual":
                stats["manual_needed"] += 1
            elif len(fit["allocations"]) > 1:
                stats["splits"] += 1
            nodes[pkey] = {"node_key": pkey, "kind": "picture",
                           "request_hash": key, "takes": [],
                           "consumers": set(), "request": t["request"],
                           "provider": provider, "model": model,
                           "allocations": fit["allocations"],
                           "status": ("needs_manual"
                                      if fit["status"] == "needs_manual"
                                      else "planned"),
                           "problem": fit.get("reason", ""),
                           "depends": []}
            by_req[key] = pkey
        n = nodes[pkey]
        n["takes"].append({"variant": t["variant"], "slot": t["slot"],
                           "duration_s": t["duration_s"], "handle_s": t.get("handle_s", 0)})
        n["consumers"].add(t["variant"])
    for n in nodes.values():
        n["consumers"] = sorted(n["consumers"])
    stats["unique_pictures"] = len(nodes)
    stats["shared_pictures"] = sum(
        1 for n in nodes.values() if len(n["consumers"]) > 1)
    # downstream: download per picture; review/compose/deliver per variant
    variants = sorted({t["variant"] for t in takes})
    for key, n in list(nodes.items()):
        dkey = f"dl:{n['request_hash']}"
        nodes[dkey] = {"node_key": dkey, "kind": "download",
                       "request_hash": n["request_hash"],
                       "consumers": n["consumers"], "takes": n["takes"],
                       "status": "planned", "depends": [n["node_key"]],
                       "allocations": [], "request": {},
                       "provider": n["provider"], "model": n["model"],
                       "problem": ""}
    for v in variants:
        pic_keys = [k for k, n in nodes.items() if n["kind"] == "picture"
                    and v in n["consumers"]]
        dl_keys = [f"dl:{nodes[k]['request_hash']}" for k in pic_keys]
        rkey = f"rev:{v}"
        nodes[rkey] = {"node_key": rkey, "kind": "review",
                       "consumers": [v], "takes": [], "status": "planned",
                       "depends": dl_keys, "allocations": [],
                       "request": {}, "provider": "", "model": "",
                       "request_hash": "", "problem": ""}
        ckey = f"cmp:{v}"
        nodes[ckey] = {"node_key": ckey, "kind": "compose",
                       "consumers": [v], "takes": [], "status": "planned",
                       "depends": [rkey], "allocations": [],
                       "request": {}, "provider": "", "model": "",
                       "request_hash": "", "problem": ""}
        dkey = f"del:{v}"
        nodes[dkey] = {"node_key": dkey, "kind": "deliver",
                       "consumers": [v], "takes": [], "status": "planned",
                       "depends": [ckey], "allocations": [],
                       "request": {}, "provider": "", "model": "",
                       "request_hash": "", "problem": ""}
    return {"nodes": nodes, "stats": stats}


def downstream_blocked(nodes, node_key):
    """Variant keys whose chains depend on a node — for branch
    isolation (rejecting C's shot must not touch A/B/D)."""
    consumers = set(nodes[node_key].get("consumers", []))
    blocked = set()
    for k, n in nodes.items():
        if node_key in n.get("depends", []):
            blocked |= set(n.get("consumers", []))
    return sorted(consumers & blocked) or sorted(consumers)


def readiness(nodes):
    """Missing/rejected/uncertain/ready buckets for resume evidence."""
    out = {"ready": [], "missing": [], "rejected": [], "uncertain": [],
           "needs_manual": [], "done": []}
    for k, n in nodes.items():
        s = n.get("status", "planned")
        if s in ("accepted", "done", "downloaded"):
            out["done"].append(k)
        elif s == "rejected":
            out["rejected"].append(k)
        elif s in ("uncertain", "failed"):
            out["uncertain"].append(k)
        elif s == "needs_manual":
            out["needs_manual"].append(k)
        elif all(nodes[d].get("status") in
                 ("accepted", "done", "downloaded")
                 for d in n.get("depends", [])):
            out["ready"].append(k)
        else:
            out["missing"].append(k)
    return out
