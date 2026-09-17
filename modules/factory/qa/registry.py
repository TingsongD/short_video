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
IMPLEMENTED = {"F00", "F01", "F02", "F03", "F04"}

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
}


def _default_expected(module, n):
    return EXPECTED.get(f"{module}-M{n:02d}",
                        f"{module} manual case {n} (see module guide)")


def all_cases():
    """The full 144-case registry; impl callables attach in case modules."""
    from . import cases_f01, cases_f02, cases_f03, cases_f04
    impls = {**cases_f01.implementations(), **cases_f02.implementations(),
             **cases_f03.implementations(), **cases_f04.implementations()}
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
