"""Job DAG validation (F06 checklist 1): cycle detection, unmet
dependency checks and blocked-descendant reasons — all before a plan is
accepted."""
from ..domain.errors import ContractError


class DagError(ContractError):
    pass


def validate_dag(jobs):
    """jobs: iterable of objects with .id and .depends_on.
    Returns topo order (list of ids) or raises DagError."""
    ids = {}
    for j in jobs:
        if j.id in ids:
            raise DagError("duplicate_job_id", "id", j.id)
        ids[j.id] = j
    for j in jobs:
        for dep in j.depends_on:
            if dep not in ids:
                raise DagError("unmet_dependency", j.id,
                               f"depends on unknown {dep}")
            if dep == j.id:
                raise DagError("self_dependency", j.id)
    order, state = [], {}

    def visit(jid, stack):
        if state.get(jid) == "done":
            return
        if state.get(jid) == "visiting":
            raise DagError("cycle", "depends_on",
                           " -> ".join(stack + [jid]))
        state[jid] = "visiting"
        for dep in ids[jid].depends_on:
            visit(dep, stack + [jid])
        state[jid] = "done"
        order.append(jid)

    for j in jobs:
        visit(j.id, [])
    return order


def dependents(jobs):
    """job_id -> [ids that depend on it]."""
    out = {j.id: [] for j in jobs}
    for j in jobs:
        for dep in j.depends_on:
            out[dep].append(j.id)
    return out


def block_descendants(jobs, failed_id, reason, failed_ids):
    """Mark every descendant of failed_id blocked with a reason chain.
    `failed_ids` accumulates statuses externally."""
    deps = dependents(jobs)
    blocked = []
    stack = list(deps.get(failed_id, []))
    seen = set()
    while stack:
        jid = stack.pop()
        if jid in seen:
            continue
        seen.add(jid)
        blocked.append(jid)
        stack.extend(deps.get(jid, []))
    return blocked
