"""F28 manual scenarios: operator-driven UI flows. The component and
contract tests (apps/factory-dashboard, 15 vitest cases) cover the
automatable portion; these cases require a human at the dashboard."""
from .cases_f01 import CaseContext, _result


def f28_m01(ctx: CaseContext):
    """Empty workspace → import fixture, select three products, review
    blueprint, create four plans — all through the UI."""
    return _result(ctx, "awaiting_manual_review",
                   "operator walkthrough required: nontechnical "
                   "import→select→review→plan flow; component states "
                   "verified by vitest (15 tests)")


def f28_m02(ctx: CaseContext):
    """Toggle provider policy; insufficient-credit/unqualified states
    must update costs and block unsupported runnable plans."""
    return _result(ctx, "awaiting_manual_review",
                   "policy toggle is a UI action; granular readiness "
                   "and blocked-plan logic verified by vitest")


def f28_m03(ctx: CaseContext):
    """Approve quote, edit copy in a second tab, Run in the first —
    stale revision must be understandable and unfundable."""
    return _result(ctx, "awaiting_manual_review",
                   "two-tab staleness is a human interaction; the "
                   "stale→409→re-quote path is verified by vitest and "
                   "the F27 API tests")


def f28_m04(ctx: CaseContext):
    """Keyboard navigation at narrow width; empty/error/reconnect
    screens; no secrets or raw CLI output required."""
    return _result(ctx, "awaiting_manual_review",
                   "accessibility/keyboard audit is human; aria "
                   "labels, state screens and secret-free surfaces "
                   "are covered by vitest")


def implementations():
    return {"F28-M01": f28_m01, "F28-M02": f28_m02,
            "F28-M03": f28_m03, "F28-M04": f28_m04}
