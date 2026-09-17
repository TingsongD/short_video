"""Case registry: all 144 Fxx-Mnn manual scenarios (module guide).

Every case is registered with its module, level and expected outcome so
`cases` reports real status. A case's callable is supplied by its module;
absent implementation reports not_implemented / missing_prerequisite —
never a canned pass.
"""
from dataclasses import dataclass, field


@dataclass
class CaseSpec:
    id: str
    module: str
    level: str                       # offline | connected | live
    expected: str
    prerequisites: tuple = ()
    impl: object = None              # callable(ctx) -> dict


MODULES = {
    "F00": {"name": "Baseline and engineer onboarding"},
    "F01": {"name": "QA harness, deterministic fixtures and fake providers"},
    "F02": {"name": "Factory contracts and immutable revisions"},
    "F03": {"name": "SQLite store and migrations"},
    "F04": {"name": "Artifact registry, media intake and provenance"},
    "F05": {"name": "Prices, budgets, approvals and reservations"},
    "F06": {"name": "Dependency scheduler, capacities and leases"},
    "F07": {"name": "Submission recovery and retry policy"},
    "F08": {"name": "Events, timing and observability"},
    "F09": {"name": "Seed registry and source acquisition"},
    "F10": {"name": "Outlier discovery and baseline evidence"},
    "F11": {"name": "Shopify product and media snapshots"},
    "F12": {"name": "Reference analysis and blueprint review"},
    "F13": {"name": "Reusable format and template authoring"},
    "F14": {"name": "Experiment, control and treatment planning"},
    "F15": {"name": "Shared generation contract and provider routing"},
    "F16": {"name": "Official Jimeng Canvas adapter"},
    "F17": {"name": "Google Vertex video adapter"},
    "F18": {"name": "Product, presenter and outfit references"},
    "F19": {"name": "TTS, speech fitting and alignment"},
    "F20": {"name": "Music, sound and shared mix"},
    "F21": {"name": "Unique-work production plan and asset graph"},
    "F22": {"name": "Hypit composition compiler and asset binding"},
    "F23": {"name": "Render execution and output retrieval"},
    "F24": {"name": "Technical, creative and changed-region QC"},
    "F25": {"name": "Verified Google Drive delivery"},
    "F26": {"name": "Process ownership and resource cleanup"},
    "F27": {"name": "Application API and local security"},
    "F28": {"name": "Dashboard seed, planner and budget screens"},
    "F29": {"name": "Queue, comparison, review and Studio feedback UI"},
    "F30": {"name": "Local installation, services and backup/restore"},
    "F31": {"name": "Manual and authorized automated publishing"},
    "F32": {"name": "Analytics readback and coverage"},
    "F33": {"name": "Experiment decisions and learning library"},
    "F34": {"name": "Failure drills and performance qualification"},
    "F35": {"name": "Funded pilot, release and engineer handoff"},
}

# Modules whose service code exists. Grows as phases land; a case can only
# run when its module is in this set.
IMPLEMENTED = {"F00", "F01", "F02", "F03", "F04", "F05", "F06", "F07",
               "F08", "F09", "F10", "F11", "F12", "F13", "F14",
               "F15", "F16", "F17", "F18", "F19"}

LIVE_CASES = {  # cases that can only qualify under funded/connected scope
    "F16-M04", "F17-M04", "F25-M04", "F31-M04", "F32-M04",
    "F35-M01", "F35-M02", "F35-M03", "F35-M04",
}
CONNECTED_CASES = {"F09-M01", "F10-M04", "F11-M03"}

EXPECTED = {
    "F00-M01": "clean env reproduces baseline; exact install steps exist",
    "F00-M02": "offline dev works; each live service shown unavailable",
    "F00-M03": "every change explained; frozen files and ledger unchanged",
    "F00-M04": "restore preserves spending history; scope links readable",
    "F01-M01": "deterministic data, stable identity, no duplicate effects on repeat",
    "F01-M02": "absent module, unknown fault and occupied init each error clearly",
    "F01-M03": "fake provider retains op; acceptance vs acknowledgement distinguished",
    "F01-M04": "manual verdict required before pass; report includes reviewer+hash",
    "F02-M01": "30 s/6-beat and 169.7 s/20-take plans validate; totals 900 and 5,091 frames",
    "F02-M02": "overlap, unknown provenance and zero denominator each get typed field errors",
    "F02-M03": "accepted revision immutable; edit creates child with parent hash + reason",
    "F02-M04": "compatible Jimeng converts and validates; Vertex/long-haul refuse with reasons",
    "F03-M01": "IDs, revisions and events survive restart; projections match history",
    "F03-M02": "second writer gets stale-revision conflict; first write intact",
    "F03-M03": "committed intent reconcilable after crash; no partial children",
    "F03-M04": "live-DB backup restores clean; newer schema refused before writes",
    "F04-M01": "one blob serves both source records; stream facts visible",
    "F04-M02": "thumbnail-as-video, corrupt and short clips rejected with reasons",
    "F04-M03": "interrupted transfer classified; no half-written artifact",
    "F04-M04": "unknown/traversal/symlink refused; secrets never served",
    "F05-M01": "concurrent 60+50 on 100 cap: one commits, zero submissions for loser",
    "F05-M02": "aggregate cap blocks despite sublimit; credits never pay USD",
    "F05-M03": "ambiguous hold survives restart; no phantom headroom",
    "F05-M04": "edited plan / stale quote block; exact authorized revision proceeds",
    "F06-M01": "global 5/1/1 across workers; completion releases slot; deps promote",
    "F06-M02": "pause stops new dispatch; accepted work still observed/collected",
    "F06-M03": "replacement reclaims; stale fencing rejected; no duplicate op",
    "F06-M04": "disk pressure + vertex throttle block selectively; collection continues",
    "F07-M01": "crash after acceptance reconciles one effect by hash; no resubmit",
    "F07-M02": "resumes poll original op ID; no new generation",
    "F07-M03": "download failure retries transfer only; bytes hash-verified",
    "F07-M04": "fallback suppressed until terminal cancel; resolution needs evidence",
    "F08-M01": "each delay attributed to its stage; totals reconcile",
    "F08-M02": "reconnect replays missed events once; snapshot agrees",
    "F08-M03": "secrets absent from diagnostics; safe refs survive",
    "F08-M04": "expired cursor gets resync route; health names owner+action",
    "F09-M01": "two URL forms merge to one seed; usable source artifact",
    "F09-M02": "thumbnail download → needs_source_media; import action named",
    "F09-M03": "interrupted transfer resumes same attempt; analysis unblocks",
    "F09-M04": "private/unsupported/expired targets refused or refreshed",
    "F10-M01": "100× followers, 50× mean+median baseline, seed excluded",
    "F10-M02": "only 20,001 passes >2; all 4 modes use declared denominators",
    "F10-M03": "missing ratios null; small/stale cohorts flagged+explained",
    "F10-M04": "partial coverage explicit; cache survives restart; no top-up",
    "F11-M01": "2 pages→4 snapshots; all media artifacts; 3-item selection",
    "F11-M02": "back-detail gap explicit; no inferred construction claims",
    "F11-M03": "missing_scope named; old snapshots+bytes still served",
    "F11-M04": "price change → revision 1; pinned rev 0 intact for running plan",
    "F12-M01": "six beats tile 900 frames; transcript+evidence; accept exact hash",
    "F12-M02": "169.7 s → 5091 frames; 20 beats; final CTA preserved",
    "F12-M03": "audio/speech/music unknown; accept blocked on named flags",
    "F12-M04": "lost-ack resume → same op; edit → rev2 + parent hash + stale deps",
    "F13-M01": "6 slots/900f, image refs; no source names/copy embedded",
    "F13-M02": "under-min slot + handle-less crossfade named before generation",
    "F13-M03": "static→ffmpeg_fast, animated→hypit, unknown effect named",
    "F13-M04": "caption rev2; rev1 appearance intact for pinned plan",
    "F14-M01": "A=900f; B 0-120, C 360-510, D 780-900; all branch rev1",
    "F14-M02": "undeclared music/product changes rejected + explained",
    "F14-M03": "narration change carries speech/captions/picture in region",
    "F14-M04": "control revise → variants/prices stale; old hash rejected",
    "F15-M01": "explicit jimeng+vertex routes; identical decision contract",
    "F15-M02": "duration/ref/unqualified blocked; zero submissions",
    "F15-M03": "expired+out-of-scope blocks; scoped USD auth routes vertex",
    "F15-M04": "unknown original suppresses eligible fallback",
    "F16-M01": "recoverable prep, native credits, zero ops pre-authority",
    "F16-M02": "2/5 accepted preserved; interrupt recovery, no duplicates",
    "F16-M03": "expired login named; wrong-account rejected; same-op resume",
    "F16-M04": "live gate blocked offline; fake success never qualifies",
    "F17-M01": "accepted/error/completed differ; usage is an estimate",
    "F17-M02": "expired OAuth named; same interaction resumes, no new POST",
    "F17-M03": "ambiguous POST unresolved; safe download retry same ID",
    "F17-M04": "live gate: only the tested model/location/mode qualifies",
    "F18-M01": "3-role pack accepted with sources; shared hash",
    "F18-M02": "pattern/detail/overlay defects rejected; dispatch blocked",
    "F18-M03": "lost-ack image request recovered; no duplicate op",
    "F18-M04": "presenter swap lists bound jobs/reviews; pack stale",
    "F19-M01": "segments voiced+aligned; captions inside 900 frames",
    "F19-M02": "too-long/excess-silence block for copy revision, not clips",
    "F19-M03": "hook-only change; body/cta byte-identical reuse",
    "F19-M04": "lost TTS ack reconciles; download retries transfer only",
}


def _default_expected(module, n):
    return EXPECTED.get(f"{module}-M{n:02d}",
                        f"{module} manual case {n} (see module guide)")


def all_cases():
    """The full 144-case registry; impl callables attach in case modules."""
    from . import (cases_f01, cases_f02, cases_f03, cases_f04,
                   cases_f05, cases_f06, cases_f07, cases_f08, cases_f09,
                   cases_f10, cases_f11, cases_f12, cases_f13, cases_f14,
                   cases_f15, cases_f16, cases_f17, cases_f18, cases_f19)
    impls = {**cases_f01.implementations(), **cases_f02.implementations(),
             **cases_f03.implementations(), **cases_f04.implementations(),
             **cases_f05.implementations(), **cases_f06.implementations(),
             **cases_f07.implementations(), **cases_f08.implementations(),
             **cases_f09.implementations(), **cases_f10.implementations(),
             **cases_f11.implementations(), **cases_f12.implementations(),
             **cases_f13.implementations(), **cases_f14.implementations(),
             **cases_f15.implementations(),
             **cases_f16.implementations(),
             **cases_f17.implementations(),
             **cases_f18.implementations(),
             **cases_f19.implementations()}
    specs = {}
    for mid in MODULES:
        for n in range(1, 5):
            cid = f"{mid}-M{n:02d}"
            level = ("live" if cid in LIVE_CASES else
                     "connected" if cid in CONNECTED_CASES else "offline")
            specs[cid] = CaseSpec(
                id=cid, module=mid, level=level,
                expected=_default_expected(mid, n),
                prerequisites=(mid,),
                impl=impls.get(cid))
    specs["SELF-CHECK"] = CaseSpec(
        id="SELF-CHECK", module="F01", level="offline",
        expected="harness creates fixture, fake provider and evidence",
        prerequisites=("F01",), impl=impls.get("SELF-CHECK"))
    return specs


def case_status(spec):
    if spec.impl is None:
        return ("missing_prerequisite" if spec.module not in IMPLEMENTED
                else "not_implemented")
    return "implemented"
