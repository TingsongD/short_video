"""Bounded retry policies (F07 checklist 6): cause → next action +
backoff + audit. A policy never resets an ambiguous attempt to ready —
human resolution requires evidence."""
from ..domain.errors import ContractError

# cause -> (max retries, backoff seconds, action when retries exhausted)
DEFAULT_POLICY = {
    "retryable_read":      {"max": 5, "backoff": (1, 2, 4, 8, 16),
                            "exhausted": "escalate"},
    "retryable_transfer":  {"max": 5, "backoff": (1, 2, 4, 8, 16),
                            "exhausted": "escalate"},
    "pre_acceptance":      {"max": 0, "backoff": (),
                            "exhausted": "fail"},      # safe to resubmit
    "ambiguous":           {"max": 0, "backoff": (),
                            "exhausted": "reconcile"}, # never blind-retry
    "terminal":            {"max": 0, "backoff": (),
                            "exhausted": "fail"},
    "auth":                {"max": 3, "backoff": (5, 15, 60),
                            "exhausted": "escalate"},
}


def classify(provider_code, http_status=None, where="submit"):
    """Provider error → failure class (checklist 3)."""
    if provider_code in ("rejected_before_accept",):
        return "pre_acceptance"
    if provider_code == "quota_exceeded" or http_status == 429:
        return "pre_acceptance"          # no acceptance, no charge
    if provider_code == "auth_required":
        return "auth" if where == "observe" else "pre_acceptance"
    if provider_code in ("response_lost", "malformed_ack"):
        return "ambiguous"
    if provider_code in ("generation_failed", "output_rejected"):
        return "terminal"
    if provider_code in ("operation_not_found",):
        return "terminal"                # needs evidence; not auto-retry
    if provider_code in ("download_transport_failed",
                         "output_not_available", "poll_failed"):
        return "retryable_transfer" if "download" in where \
            or "collect" in where else "retryable_read"
    return "ambiguous"                   # unknown codes are not free


def next_action(state, policy=None):
    """state: {cause, retries}. Returns dict(action, wait_s|None)."""
    policy = policy or DEFAULT_POLICY
    cause = state.get("cause", "ambiguous")
    spec = policy.get(cause, policy["ambiguous"])
    retries = state.get("retries", 0)
    if retries < spec["max"]:
        return {"action": "retry",
                "wait_s": spec["backoff"][min(retries,
                                             len(spec["backoff"]) - 1)],
                "cause": cause}
    return {"action": spec["exhausted"], "wait_s": None, "cause": cause}


def check_policy_ok(action):
    if action not in ("retry", "fail", "reconcile", "escalate"):
        raise ContractError("bad_retry_action", "action", action)
    return action
