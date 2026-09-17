"""Composition compiler (F22): accepted plan → deterministic
SVML/SVS/SVRun + explicit asset binding manifest.

Every picture/audio/caption asset is bound by artifact id + sha256 and
target frame interval — never discovered by folder order. Identical
inputs recompile to identical bytes; a changed selection produces a
traceable new revision. Compile errors never touch providers.
"""
import hashlib
import json
from pathlib import Path

from modules.assemble.hypit_markup import escape_markup_text
from ..domain.errors import ContractError
from ..domain.records import Composition, content_hash

ALLOWED_IMPORTS = {
    "@hypit/media@1", "@hypit/timeline-author@1", "@hypit/spatial@1",
    "@hypit/media-pipeline@1", "@hypit/media-track@1",
    "@hypit/typography-track@1", "@hypit/film@1",
    "@hypit/render-hyperframes@1", "@hypit/run-markup@1",
    "@hypit/svs@1", "./style.svs"}

# declared renderer capabilities — effects a renderer can express
RENDERER_EFFECTS = {
    "hypit": {"cut", "crossfade", "kenburns", "inset", "title",
              "caption"},
    "ffmpeg_fast": {"cut", "crossfade", "caption"}}


def _sec(frames, fps):
    return f"{frames / fps:.3f}s"


class CompositionService:
    def __init__(self, db, artifacts, root):
        self.db = db
        self.artifacts = artifacts
        self.root = Path(root)

    # -------------------------------------------------------- compile

    def compile(self, comp_id, experiment_id, variant_key, plan_id,
                segments, captions, clock, renderer="hypit",
                plan_hash="", now=""):
        """segments: [{id,kind:picture|audio,artifact_id,sha256,
                      in_frame,out_frame,source_in_s,source_out_s,
                      effects?}]
        captions: [{id,text,start_frame,end_frame,placement}]
        → {"composition": dict, "diagnostics": [...]} — diagnostics
        non-empty ⇒ status failed and NO files are emitted."""
        fps = clock["fps"]
        diags = self._diagnose(segments, captions, clock, renderer)
        if diags:
            comp = self._persist(comp_id, experiment_id, variant_key,
                                 plan_id, clock, renderer, "failed",
                                 [], {}, plan_hash, diags, now)
            return {"composition": comp, "diagnostics": diags}
        total_frames = max(
            [s["out_frame"] for s in segments]
            + [c["end_frame"] for c in captions] + [0])
        svml, bindings = self._emit_svml(segments, captions, clock,
                                       total_frames)
        svs = self._emit_svs()
        svrun = ('<?svml using="@hypit/run-markup@1"?>\n'
                 '<svrun version="1">\n'
                 '  <author source="./video.svml"/>\n'
                 '  <target output="final.video"/>\n</svrun>\n')
        files = {"video.svml": svml, "style.svs": svs,
                 "render.svrun": svrun}
        file_hashes = {k.split(".")[-1].replace("svml", "svml"):
                       hashlib.sha256(v.encode()).hexdigest()
                       for k, v in files.items()}
        # revision chain: same content → same revision; changed → next
        prev = self._latest(experiment_id, variant_key)
        manifest = {"schema_version": "composition_manifest.v1",
                    "composition_id": comp_id,
                    "experiment_id": experiment_id,
                    "variant_key": variant_key,
                    "plan_id": plan_id, "plan_hash": plan_hash,
                    "renderer": renderer, "clock": clock,
                    "total_frames": total_frames,
                    "bindings": bindings}
        manifest_bytes = json.dumps(manifest, indent=1,
                                    sort_keys=True) + "\n"
        files["manifest.json"] = manifest_bytes
        file_hashes = {k: hashlib.sha256(
            v.encode() if isinstance(v, str) else v).hexdigest()
            for k, v in files.items()}
        content = content_hash({k: file_hashes[k] for k in
                                sorted(file_hashes)})
        if prev and prev["content_hash"] == content:
            return {"composition": prev, "diagnostics": [],
                    "reused_revision": True}
        revision = (prev["revision"] + 1) if prev else 1
        out_dir = self.root / comp_id / f"r{revision}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (out_dir / name).write_text(text)
        # materialize bound assets — sources are relative to the svml
        assets_dir = out_dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        for s in segments:
            src = self.artifacts.path_for(s["artifact_id"])
            ext = "wav" if s["kind"] == "audio" else "mp4"
            dst = assets_dir / f"{s['id']}.{ext}"
            dst.write_bytes(Path(src).read_bytes())
        comp = self._persist(comp_id, experiment_id, variant_key,
                             plan_id, clock, renderer, "draft",
                             bindings, file_hashes, plan_hash, [], now,
                             revision=revision,
                             parent_revision=(prev["revision"]
                                              if prev else 0),
                             parent_hash=(prev["content_hash"]
                                          if prev else ""),
                             total_frames=total_frames,
                             content=content)
        return {"composition": comp, "diagnostics": [],
                "files": {k: str(out_dir / k) for k in files}}

    # ---------------------------------------------------- diagnostics

    def _diagnose(self, segments, captions, clock, renderer):
        """Readable compile diagnostics with exact locations."""
        diags = []
        allowed = RENDERER_EFFECTS.get(renderer, set())
        for s in segments:
            loc = f"segment[{s['id']}]"
            art = self.db.uow().artifacts.get(s["artifact_id"]) \
                if s.get("artifact_id") else None
            if art is None:
                diags.append({"code": "missing_asset", "at": loc,
                              "detail": s.get("artifact_id")})
                continue
            if s.get("sha256") and s["sha256"] != art["sha256"]:
                diags.append({"code": "stale_selection", "at": loc,
                              "detail": f"bound sha {s['sha256'][:12]}"
                                        f" != artifact "
                                        f"{art['sha256'][:12]}"})
            need = s.get("source_out_s", 0) - s.get("source_in_s", 0)
            probe = json.loads(art["probe"] or "{}")
            have = probe.get("duration_s")
            if have is not None and need > have + 1e-6:
                diags.append({"code": "insufficient_duration",
                              "at": loc,
                              "detail": f"needs {need:.3f}s of "
                                        f"{have:.3f}s"})
            for eff in s.get("effects", []):
                if eff not in allowed:
                    diags.append({"code": "unsupported_effect",
                                  "at": loc, "detail":
                                  f"{eff} not in {renderer} manifest"})
        pics = sorted((s for s in segments if s["kind"] == "picture"),
                      key=lambda s: s["in_frame"])
        for a, b in zip(pics, pics[1:]):
            if b["in_frame"] < a["out_frame"]:
                diags.append({"code": "overlap", "at":
                              f"segment[{b['id']}]",
                              "detail": f"starts {b['in_frame']} before"
                                        f" {a['id']} ends "
                                        f"{a['out_frame']}"})
        for c in captions:
            if c["end_frame"] <= c["start_frame"]:
                diags.append({"code": "bad_interval", "at":
                              f"caption[{c['id']}]", "detail": ""})
        return diags

    # --------------------------------------------------------- emit --

    def _emit_svml(self, segments, captions, clock, total_frames):
        fps, w, h = clock["fps"], clock["width"], clock["height"]
        end_s = _sec(total_frames, fps)
        pics = sorted((s for s in segments if s["kind"] == "picture"),
                      key=lambda s: s["in_frame"])
        auds = sorted((s for s in segments if s["kind"] == "audio"),
                      key=lambda s: s["in_frame"])
        lines = ['<?svml using="@hypit/markup@1"?>', '<svml>',
                 '  <import as="asset" from="@hypit/media@1"/>',
                 '  <import as="time" from="@hypit/timeline-author@1"/>',
                 '  <import as="space" from="@hypit/spatial@1"/>',
                 '  <import as="pipeline" '
                 'from="@hypit/media-pipeline@1"/>',
                 '  <import as="media" from="@hypit/media-track@1"/>',
                 '  <import as="typo" '
                 'from="@hypit/typography-track@1"/>',
                 '  <import as="film" from="@hypit/film@1"/>',
                 '  <import as="render" '
                 'from="@hypit/render-hyperframes@1"/>',
                 '  <import as="look" source="./style.svs"/>', '',
                 f'  <time:Clock id="clock" frame-rate="{fps}"/>',
                 f'  <time:Timeline id="program" clock={{clock}} '
                 f'end="{end_s}"/>',
                 f'  <space:Canvas id="canvas" width="{w}" '
                 f'height="{h}"/>',
                 '  <space:Frame id="full" within={canvas} left="0%"'
                 ' top="0%" right="100%" bottom="100%"/>',
                 '  <space:Frame id="heading" within={canvas} left="7%"'
                 ' top="74%" right="93%" bottom="86%"/>', '']
        bindings = []
        # explicit asset elements, one per segment binding
        for s in pics + auds:
            tag = "Video" if s["kind"] == "picture" else "Audio"
            ext = "wav" if s["kind"] == "audio" else "mp4"
            lines.append(f'  <asset:{tag} id="src-{s["id"]}" '
                         f'src="./assets/{s["id"]}.{ext}"/>')
            bindings.append({"binding": f"src-{s['id']}",
                             "role": s["kind"],
                             "artifact_id": s["artifact_id"],
                             "sha256": s["sha256"],
                             "in_frame": s["in_frame"],
                             "out_frame": s["out_frame"],
                             "track": ("picture" if s["kind"] ==
                                       "picture" else "audio")})
        for s in pics:
            lines.append(
                f'  <pipeline:Normalize id="norm-{s["id"]}" '
                f'source={{src-{s["id"]}}} clock={{clock}} '
                f'video="primary-moving" audio="default" '
                f'span-authority="video"/>')
        lines += ['', '  <media:Track id="footage" '
                  'timeline={program.timeline} canvas={canvas}>']
        for s in pics:
            effects = s.get("effects") or []
            attrs = (f' playback="{effects[0]}"' if effects and
                     effects[0] in ("kenburns",) else "")
            lines.append(
                f'    <media:Item id="{s["id"]}" '
                f'media={{norm-{s["id"]}.media}} frame={{full}} '
                f'appearance={{look.media.full}} '
                f'start="{_sec(s["in_frame"], fps)}" '
                f'end="{_sec(s["out_frame"], fps)}"'
                f'{attrs} source-audio="none"/>')
        lines.append('  </media:Track>')
        if auds:
            lines += ['', '  <media:Track id="sound" '
                      'timeline={program.timeline} canvas={canvas}>']
            for s in auds:
                lines.append(
                    f'    <media:Item id="{s["id"]}" '
                    f'media={{src-{s["id"]}.media}} frame={{full}} '
                    f'appearance={{look.media.full}} '
                    f'start="{_sec(s["in_frame"], fps)}" '
                    f'end="{_sec(s["out_frame"], fps)}" '
                    f'source-audio="content"/>')
            lines.append('  </media:Track>')
        if captions:
            lines += ['', '  <typo:Style id="cap" '
                      'recipe={look.text.caption}>',
                      '    <typo:Fill color="#ffffff"/>',
                      '  </typo:Style>',
                      '  <typo:Track id="captions" '
                      'timeline={program.timeline}>']
            for c in sorted(captions,
                            key=lambda c: c["start_frame"]):
                text = escape_markup_text(c["text"])
                place = c.get("placement", "heading")
                lines.append(
                    f'    <typo:Area id="{c["id"]}" '
                    f'placement={{{place}}} style={{cap}} '
                    f'start="{_sec(c["start_frame"], fps)}" '
                    f'end="{_sec(c["end_frame"], fps)}">'
                    f'{text}</typo:Area>')
                bindings.append({"binding": c["id"], "role": "caption",
                                 "artifact_id": "",
                                 "sha256": hashlib.sha256(
                                     c["text"].encode()).hexdigest(),
                                 "in_frame": c["start_frame"],
                                 "out_frame": c["end_frame"],
                                 "track": "captions"})
            lines.append('  </typo:Track>')
        lines += ['', '  <film:Film id="main" canvas={canvas} '
                  'timeline={program.timeline} '
                  'appearance={look.film.main}>',
                  '    <film:Track source={footage.visual}/>',
                  '    <film:Track source={footage.audio}/>']
        if auds:
            lines.append('    <film:Track source={sound.audio}/>')
        if captions:
            lines.append('    <film:Track source={captions.track}/>')
        lines += ['  </film:Film>',
                  '  <render:Video id="final" '
                  'composition={main.composition} '
                  'timeline={program.timeline}/>', '</svml>', '']
        return "\n".join(lines), bindings

    def _emit_svs(self):
        return ('<?svml using="@hypit/svs@1"?>\n'
                '<sheet version="1">\n'
                '  film.main { background: #000000; }\n'
                '  media.full { stack-order: 0; fit: cover; }\n'
                '  text.caption { size: 64; weight: 600; '
                'line-height: 1.2; align: start; '
                'block-align: center; stack-order: 20; }\n'
                '</sheet>\n')

    # -------------------------------------------------------- persist

    def _persist(self, comp_id, experiment_id, variant_key, plan_id,
                 clock, renderer, status, bindings, file_hashes,
                 plan_hash, diags, now, revision=1, parent_revision=0,
                 parent_hash="", total_frames=0, content=""):
        comp = Composition(
            schema_version="composition.v1", id=comp_id, created_at=now,
            experiment_id=experiment_id, variant_key=variant_key,
            revision=revision, parent_revision=parent_revision,
            parent_hash=parent_hash, plan_id=plan_id, status=status,
            renderer=renderer, clock=clock, total_frames=total_frames,
            files=file_hashes, bindings=bindings,
            source_revisions={"plan_id": plan_id,
                              "plan_hash": plan_hash},
            content_hash=content, diagnostics=diags)
        comp.validate_or_raise()
        row = self.db.uow().records.get("composition", comp_id, revision)
        with self.db.uow() as u:
            if row is None:
                u.records.put(comp)
            else:
                if row["content_hash"] != comp.content_hash:
                    raise ContractError("immutable_revision", "composition", comp_id)
                return json.loads(row["body"])
        return comp.to_dict()

    def _latest(self, experiment_id, variant_key):
        """Latest SUCCESSFUL revision — failed compiles persist for
        audit but never consume a revision number."""
        rows = self.db.conn.execute(
            "SELECT body FROM records WHERE kind='composition' AND "
            "json_extract(body,'$.experiment_id')=? AND "
            "json_extract(body,'$.variant_key')=? AND "
            "json_extract(body,'$.status')!='failed' ORDER BY "
            "json_extract(body,'$.revision') DESC LIMIT 1",
            (experiment_id, variant_key)).fetchall()
        return json.loads(rows[0]["body"]) if rows else None

    def get(self, comp_id):
        row = self.db.uow().records.get("composition", comp_id)
        return json.loads(row["body"]) if row else None
