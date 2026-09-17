"""Mix service (F20): one frozen profile per experiment revision —
speech/music gains, duck envelope, rate/channels, clip policy and a
MEASURED loudness target. Deterministic PCM render; unchanged regions
provably share the same parameters.
"""
import hashlib
import json

from ..domain.errors import ContractError
from ..domain.records import MixProfile, content_hash
from . import pcm


class MixService:
    def __init__(self, db, artifacts):
        self.db = db
        self.artifacts = artifacts

    # -------------------------------------------------------- profile

    def freeze(self, profile_id, experiment_id, bed_id, cfg, now=""):
        """cfg: {sample_rate,channels,speech_gain_db,music_gain_db,duck,
        loudness_target,clip_policy}. Freezing pins profile_hash —
        variant copy edits cannot alter the music master."""
        prof = MixProfile(schema_version="mix_profile.v1", id=profile_id,
                          created_at=now, experiment_id=experiment_id,
                          music_bed_id=bed_id,
                          sample_rate=cfg.get("sample_rate", pcm.RATE),
                          channels=cfg.get("channels", 1),
                          speech_gain_db=cfg.get("speech_gain_db", 0.0),
                          music_gain_db=cfg.get("music_gain_db", -14.0),
                          duck=dict(cfg.get("duck") or {}),
                          loudness_target=dict(
                              cfg.get("loudness_target") or {}),
                          clip_policy=cfg.get("clip_policy", "prevent"),
                          status="frozen")
        prof.profile_hash = self._hash(prof)
        prof.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(prof)
        return prof

    def get(self, profile_id):
        row = self.db.uow().records.get("mixprofile", profile_id)
        return json.loads(row["body"]) if row else None

    def _hash(self, prof):
        d = prof.to_dict()
        d.pop("profile_hash", None)
        d.pop("created_at", None)
        return content_hash(d)

    # ------------------------------------------------------------ mix

    def mix(self, profile_id, tracks, out_s, artifact_name=""):
        """tracks: [{artifact_id|samples, gain_db, offset_s, kind:
        speech|music|sfx}]. Renders deterministic PCM, measures real
        levels, reports clipping per policy."""
        prof = self.get(profile_id)
        if prof is None:
            raise ContractError("unknown_profile", "profile_id",
                                profile_id)
        rate = prof["sample_rate"]
        out = [0] * int(round(out_s * rate))
        for t in tracks:
            if "samples" in t:
                samples = t["samples"]
            else:
                path = self.artifacts.path_for(t["artifact_id"])
                _, samples = pcm.read_wav(open(path, "rb").read())
            gain = t.get("gain_db")
            if gain is None:
                gain = (prof["speech_gain_db"] if t["kind"] == "speech"
                        else prof["music_gain_db"])
            samples = pcm.gain_db(samples, gain)
            off = int(round(t.get("offset_s", 0.0) * rate))
            out = pcm.overlay(out, samples, off)
        measured = pcm.measure(out, rate)
        clipped = measured["clipped"]
        if clipped and prof["clip_policy"] == "prevent":
            # documented repair: reduce everything by headroom, re-measure
            headroom_db = measured["peak_dbfs"] - -1.0 \
                if measured["peak_dbfs"] is not None else 0
            out = pcm.gain_db(out, -(headroom_db + 0.5))
            measured = {**pcm.measure(out, rate),
                        "repaired_db": round(headroom_db + 0.5, 2)}
            clipped = False
        wav = pcm.write_wav(out, rate, prof["channels"])
        result = {"profile_hash": prof["profile_hash"],
                  "measured": measured, "clipped": clipped,
                  "exact_samples": len(out),
                  "sha256": hashlib.sha256(wav).hexdigest()}
        if artifact_name:
            art = self.artifacts.intake_bytes(
                wav, provenance="generated_other",
                source_key=f"mix:{profile_id}:{artifact_name}",
                source_detail="frozen-profile mix",
                requested_kind="audio")
            result["artifact_id"] = art.id
        return result

    # ---------------------------------------------- region evidence --

    def region_parameters(self, profile_id, region):
        """Effective per-region parameters (gain/duck) — the evidence
        that unchanged regions are identical across variants."""
        prof = self.get(profile_id)
        duck = prof.get("duck") or {}
        applied = any(region["start_frame"] >= r.get("start",
                                                    r.get("start_frame", 0))
                      and region["end_frame"] <= r.get("end",
                                                       r.get("end_frame", 0))
                      for r in duck.get("regions", []))
        return {"music_gain_db": prof["music_gain_db"],
                "speech_gain_db": prof["speech_gain_db"],
                "duck_db": -(duck.get("amount_db", 0.0)) if applied else 0.0,
                "sample_rate": prof["sample_rate"]}

    def assert_unchanged_identical(self, profile_a, profile_b,
                                   unchanged_regions):
        """A/B evidence: every unchanged region must resolve identical
        parameters; a difference outside declared scope is a defect."""
        diffs = []
        for r in unchanged_regions:
            pa = self.region_parameters(profile_a, r)
            pb = self.region_parameters(profile_b, r)
            if pa != pb:
                diffs.append({"region": r, "a": pa, "b": pb})
        if diffs:
            raise ContractError("unchanged_region_differs",
                                "regions", json.dumps(diffs)[:300])
        return True
