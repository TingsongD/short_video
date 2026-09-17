"""F04 manual scenarios: intake, defects, recovery, containment."""
import os

from .cases_f01 import CaseContext, _result
from ..artifacts import ArtifactStore, IntakeError
from ..domain import ContractError
from ..store import Database
from ..testing import fixtures


def _fixture_dir(ctx, name):
    """Materialize a fixture on demand; deterministic per workspace."""
    dest = ctx.workspace.path / "fixtures" / name
    if not dest.exists():
        fixtures.materialize(name, ctx.workspace.path)
    return dest


def _store(ctx, name):
    db = Database(ctx.workspace.dir("store") / f"{name}.db")
    return ArtifactStore(ctx.workspace.dir("artifacts") / name, db=db)


def _defs(ctx):
    return _fixture_dir(ctx, "reference-defects")


def _good(ctx):
    return _fixture_dir(ctx, "core-30s") / "source.mp4"


def f04_m01(ctx: CaseContext):
    s = _store(ctx, "m01")
    src = _good(ctx)
    a1 = s.intake_file(src, provenance="seed_source",
                       source_key="seed:demo",
                       requested_kind="video")
    a2 = s.intake_file(src, provenance="manual",
                       source_key="drop:manual-1")
    ctx.check("single_blob", a1.id == a2.id)
    rows = s.db.conn.execute(
        "SELECT source_key FROM artifact_sources WHERE artifact_id=?",
        (a1.id,)).fetchall()
    ctx.check("both_sources", len(rows) == 2, str([r[0] for r in rows]))
    v = a1.probe["streams"][0]
    ctx.check("stream_facts", v["width"] == 360 and v["height"] == 640)
    s.db.close()
    return _result(ctx, "passed",
                   "one content-addressed blob; two source attributions; "
                   "measured stream facts on the artifact")


def f04_m02(ctx: CaseContext):
    s = _store(ctx, "m02")
    defs = _defs(ctx)
    rejects = {}
    for name, kw in (
            ("thumbnail_as_video.mp4", {"requested_kind": "video"}),
            ("corrupt.mp4", {}),
            ("zero_byte.mp4", {}),
            ("short_clip.mp4", {"requested_kind": "video",
                                "min_usable_s": 4.0}),
            ("missing_audio.mp4", {"requested_kind": "audio"})):
        try:
            s.intake_file(defs / name, provenance="manual",
                          source_key=name, **kw)
            rejects[name] = "ACCEPTED"
        except IntakeError as e:
            rejects[name] = e.code
    ctx.check("thumbnail_rejected",
              rejects["thumbnail_as_video.mp4"] == "kind_mismatch",
              rejects["thumbnail_as_video.mp4"])
    ctx.check("corrupt_rejected",
              rejects["corrupt.mp4"] in ("unprobeable", "no_streams"))
    ctx.check("short_rejected",
              rejects["short_clip.mp4"] == "duration_too_short")
    ctx.check("audio_request_on_video",
              rejects["missing_audio.mp4"] == "kind_mismatch")
    n = s.db.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
    ctx.check("none_registered", n == 0)
    s.db.close()
    return _result(ctx, "passed",
                   f"rejections: {rejects}")


def f04_m03(ctx: CaseContext):
    s = _store(ctx, "m03")
    leftover = s.root / "staging" / "half-download.part"
    leftover.write_bytes(b"\x00" * 512)
    art = s.intake_file(_good(ctx), provenance="seed_source",
                        source_key="seed:ok")
    (s.root / art.local_path).unlink()      # simulate lost blob
    report = s.recover_staging()
    ctx.check("temp_classified",
              any(x["path"].endswith("half-download.part")
                  for x in report["unreferenced_temporary"]))
    ctx.check("referenced_missing_found",
              art.id in report["referenced_missing"])
    ctx.check("no_half_accepted",
              s.db.conn.execute(
                  "SELECT COUNT(*) FROM artifacts").fetchone()[0] == 1)
    s.db.close()
    return _result(ctx, "awaiting_manual_review",
                   "interrupted transfer → unreferenced temporary; lost blob "
                   "→ referenced missing; retry reuses verified bytes",
                   limitations=["real download-resume drill is F09/F34"])


def f04_m04(ctx: CaseContext):
    s = _store(ctx, "m04")
    art = s.intake_file(_good(ctx), provenance="manual", source_key="k")
    try:
        s.path_for("art:nope")
        ctx.check("unknown_refused", False)
    except ContractError as e:
        ctx.check("unknown_refused", e.code == "unknown_artifact")
    outside = ctx.workspace.dir("secrets") / "token.txt"
    outside.write_text("do-not-read")
    s.db.conn.execute(
        "UPDATE artifacts SET local_path='../../secrets/token.txt' "
        "WHERE id=?", (art.id,))
    try:
        s.path_for(art.id)
        ctx.check("traversal_refused", False)
    except ContractError:
        ctx.check("traversal_refused", True)
    link = s.root / "blobs" / "escape.bin"
    link.unlink(missing_ok=True)
    os.symlink(outside.resolve(), link)   # absolute target → real escape
    s.db.conn.execute(
        "UPDATE artifacts SET local_path='blobs/escape.bin' WHERE id=?",
        (art.id,))
    try:
        s.path_for(art.id)
        ctx.check("symlink_refused", False)
    except ContractError as e:
        ctx.check("symlink_refused", e.code == "path_escape")
    ctx.check("secrets_unread", outside.read_text() == "do-not-read")
    s.db.close()
    return _result(ctx, "passed",
                   "unknown id, traversal and symlink escape all refused; "
                   "secrets file never served")


def implementations():
    return {"F04-M01": f04_m01, "F04-M02": f04_m02,
            "F04-M03": f04_m03, "F04-M04": f04_m04}
