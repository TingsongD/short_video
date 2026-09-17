"""F29 manual scenarios: durable-progress resume, synchronized
compare, Studio feedback→stale review, and cleanup-during-activity.
Automatable parts are covered by vitest (23) + studio pytest (7);
these cases need a human at the dashboard."""
from .cases_f01 import CaseContext, _result


def f29_m01(ctx: CaseContext):
    """Staggered completions, close browser, reopen — progress resumes
    from durable state; nothing waited on the browser."""
    return _result(ctx, "awaiting_manual_review",
                   "browser close/reopen is human; durable event-log "
                   "resume is verified by F08 events + queue reducer "
                   "tests")


def f29_m02(ctx: CaseContext):
    """Compare all four finals vs source, seek across treatment
    boundaries, inspect captions/audio."""
    return _result(ctx, "awaiting_manual_review",
                   "human playback inspection; sync-seek plumbing and "
                   "changed-region overlays are vitest-verified")


def f29_m03(ctx: CaseContext):
    """Studio comment on C → import → replace C's final → old review
    must be stale; repair has explicit proposed diff/cost."""
    return _result(ctx, "awaiting_manual_review",
                   "Studio UI flow is human; comment→proposed-change "
                   "binding and stale marking verified by studio "
                   "pytest (7) + F24 stale-review gate")


def f29_m04(ctx: CaseContext):
    """Complete A, inspect its Drive/cleanup status while B is
    active — link appears promptly, B keeps running."""
    return _result(ctx, "awaiting_manual_review",
                   "human dashboard inspection; verified-link "
                   "rendering and per-video cleanup are covered by "
                   "vitest + F26 cleanup cases")


def implementations():
    return {"F29-M01": f29_m01, "F29-M02": f29_m02,
            "F29-M03": f29_m03, "F29-M04": f29_m04}
