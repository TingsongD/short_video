"""Automated checks for the auto pipeline.

These checks are real but mechanical: they verify evidence-backed
confidence, probe generated media, and scan for black/frozen output.
They are recorded with reviewer='auto-pipeline' and check types that do
not impersonate human creative approval.
"""
import json
import subprocess


def auto_review_beats(payload, evidence=None):
    """Upgrade beat confidence only where evidence supports it.

    'reviewed' requires a visual description, a sane duration, transcript
    overlap for speech-critical roles, and — for beats the provider
    itself declared uncertain or unresolved — corroborating local visual
    evidence: a detected scene boundary anchoring the beat's start (or
    the media head). Without that anchor the declared uncertainty stands
    and the blueprint gate flags the beat for a human."""
    beats = payload.get("beats") or []
    transcript = payload.get("transcript") or []
    bounds = [float(c.get("t", -1)) for c in
              (evidence or {}).get("boundaries") or []]
    speech_critical = {"product_reveal", "proof", "hook", "cta"}
    for b in beats:
        declared = str(b.get("confidence") or "").strip().lower()
        if declared in ("uncertain", "unresolved"):
            start = float(b.get("start_s") or 0)
            anchored = start <= 0.05 or b.get("evidence_ids") or \
                any(abs(t - start) <= 0.25 for t in bounds)
            if not anchored:
                continue
        dur = (b.get("end_s") or 0) - (b.get("start_s") or 0)
        if not str(b.get("visual_event") or "").strip() or dur < 0.4:
            b["confidence"] = "uncertain"
            continue
        if b.get("role") in speech_critical:
            overlap = any(t.get("end_s", 0) > b["start_s"]
                          and t.get("start_s", 0) < b["end_s"]
                          and str(t.get("text") or "").strip()
                          for t in transcript)
            b["confidence"] = "reviewed" if overlap else "uncertain"
        else:
            b["confidence"] = "reviewed"
    payload.setdefault("evidence_ids", [])
    return payload


def transcript_observations(transcript, duration_s):
    """Fallback beats from a word-timed transcript alone — honest
    'unresolved' visuals so the blueprint gate still flags for a human."""
    beats = []
    n = len(transcript)
    for i, t in enumerate(transcript):
        role = "hook" if i == 0 else ("cta" if i == n - 1 else "body")
        beats.append({"id": f"b{i}", "role": role,
                      "start_s": round(t["start_s"], 3),
                      "end_s": round(t["end_s"], 3),
                      "visual_event": "", "confidence": "unresolved"})
    return {"beats": beats, "transcript": transcript,
            "evidence_ids": [],
            "uncertainty": ["Beats derived from the transcript only; "
                            "visual events need human description"]}


def build_sections(payload, duration_s, target_frames):
    """Understanding/timeline/treatment from the (possibly auto-reviewed)
    observations — machine-drafted, recorded as automated evidence."""
    beats = payload.get("beats") or []
    transcript = payload.get("transcript") or []
    texts = [t.get("text", "").strip() for t in transcript if t.get("text")]
    first = texts[0] if texts else (beats[0].get("visual_event", "") if beats else "")
    last = texts[-1] if texts else (beats[-1].get("visual_event", "") if beats else "")
    fps = target_frames / duration_s if duration_s else 30.0
    to_frame = lambda s: min(int(round(s * fps)), target_frames - 1)
    def seg(b):
        return {"beat": b["id"], "start_frame": to_frame(b["start_s"]),
                "end_frame": to_frame(b["end_s"]) + 1}
    understanding = {
        "premise": first or "See observed opening.",
        "progression": ", ".join(b.get("role", "beat") for b in beats) or "linear",
        "hook": (beats[0].get("visual_event") or first) if beats else first,
        "setups": "; ".join(b.get("visual_event", "") for b in beats[1:-1]
                            if b.get("visual_event")) or "See observations.",
        "payoffs": (beats[-1].get("visual_event") or last) if beats else last,
        "ending": last or "See observed ending.",
        "replay_appeal": "Music-led short loop." if not texts else
                         "Loop back to the opening line.",
        "intended_response": "watch to completion",
        "observations": [f"{b['id']} {b.get('role','beat')} "
                         f"{b['start_s']:.1f}-{b['end_s']:.1f}s: "
                         f"{b.get('visual_event') or 'no visual description'}"
                         for b in beats],
        "interpretations": [f"{b['id']} plays the {b.get('role','beat')} role"
                            for b in beats],
        "uncertainties": list(payload.get("uncertainty") or [])}
    # Provider beat times are descriptive rather than frame-authoritative and
    # commonly leave tiny gaps (for example 20.0s for a 20.201s source).
    # Timeline records must cover the verified media duration exactly, so let
    # each beat own any silence before the next beat and clamp the final tail.
    ordered = sorted(beats, key=lambda b: float(b.get("start_s", 0)))
    timeline = []
    for i, b in enumerate(ordered):
        start = 0.0 if i == 0 else max(
            0.0, min(float(b.get("start_s", 0)), duration_s))
        own_end = max(start, min(float(b.get("end_s", start)),
                                 duration_s))
        if i + 1 < len(ordered):
            next_start = max(start, min(
                float(ordered[i + 1].get("start_s", own_end)),
                duration_s))
            end = max(own_end, next_start)
        else:
            end = duration_s
        if end <= start:
            continue
        timeline.append({"phase": b.get("role", "beat"),
                         "start_s": start, "end_s": end,
                         "summary": b.get("visual_event") or
                         "observed beat"})
    treatment = {
        "style": ("Automated adaptation: keep the observed premise, hook "
                  "order and beat structure; reshoot with original "
                  "characters and generated footage."),
        "changes": ("Light paraphrase of the observed narration for "
                    "variant A; B/C/D change one declared beat each."),
        "music": "Clean instrumental bed at low gain; drop if unusable.",
        "captions": ("Derived from generated narration alignment — not "
                     "forced into the source's timestamps."),
        "prompt_notes": ("Shared style: vertical 9:16, consistent "
                         "presenter, natural lighting, no text or logos.")}
    return {"understanding": understanding, "timeline": timeline,
            "treatment": treatment, "segments": [seg(b) for b in beats]}


def _ffmpeg_report(path, vf):
    """Filter output, or None when the scan never actually ran —
    a missing binary, timeout, or nonzero exit must not be mistaken
    for a clean result downstream."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
           "-vf", vf, "-f", "null", "-"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    return p.stderr or ""


def inspect_asset(path, info, expected):
    """Technical checks on a generated artifact. `info` is the stored
    probe JSON ({streams, duration_s, …}); `expected` carries
    {min_duration_s, min_height, kind}. → (verdict, notes)"""
    notes = []
    if not path:
        return "fail", ["artifact missing"]
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"),
                 None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"),
                 None)
    if video is None and audio is None:
        return "fail", ["artifact has no media streams"]
    image_codecs = {"png", "mjpeg", "bmp", "webp", "tiff", "gif"}
    kind = "image" if video and video.get("codec_name") in image_codecs \
        and video.get("nb_frames") in (None, 1, "1") else \
        ("video" if video else "audio")
    expected_kind = expected.get("kind", "video")
    if expected_kind == "video" and kind == "audio":
        notes.append("expected video, probed audio only")
    dur = float(info.get("duration_s") or 0.0)
    need = expected.get("min_duration_s") or 0.0
    if kind == "video" and dur + 0.05 < need:
        notes.append(f"duration {dur:.2f}s below needed {need:.2f}s")
    if expected.get("min_height") and video:
        if min(video.get("width", 0), video.get("height", 0)) < \
                expected["min_height"]:
            notes.append("resolution below requested")
    if notes:
        return "fail", notes
    if kind != "video" or dur < 0.5:
        return "pass", notes or ["checked: container, duration, resolution"]
    black = _ffmpeg_report(path, "blackdetect=d=0.1:pix_th=0.10")
    if black is None:
        return "uncertain", ["black-frame scan did not run "
                             "(ffmpeg unavailable or failed)"]
    total = 0.0
    for line in black.splitlines():
        if "blackdetect" not in line or "black_start" not in line:
            continue
        fields = dict(part.split(":", 1) for part in line.split()
                      if ":" in part)
        try:
            total += float(fields["black_end"]) - \
                float(fields["black_start"])
        except (KeyError, ValueError):
            continue
    if total / dur > 0.6:
        return "fail", [f"mostly black frames ({total:.1f}s of {dur:.1f}s)"]
    freeze = _ffmpeg_report(path, "freezedetect=n=-60dB:d=1.5")
    if freeze is None:
        return "uncertain", ["freeze-frame scan did not run "
                             "(ffmpeg unavailable or failed)"]
    if "freeze_start" in freeze:
        notes.append("frozen frames detected (>1.5s)")
        return "fail", notes
    return "pass", notes or ["checked: container, duration, resolution, "
                             "black/frozen scan"]
