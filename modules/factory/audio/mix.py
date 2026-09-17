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
        rate, channels = prof["sample_rate"], prof["channels"]
        if rate <= 0 or channels not in (1,2) or out_s <= 0:
            raise ContractError("invalid_mix_clock", "profile")
        frames = int(round(out_s * rate))
        out = [0.0] * (frames*channels)
        duck = prof.get("duck") or {}
        regions = duck.get("regions", []) if duck.get("enabled", False) else []
        fps = duck.get("fps", 30)
        for t in tracks:
            if "samples" in t:
                mono = pcm.resample(t["samples"], t.get("sample_rate", pcm.RATE), rate)
                samples = [v for v in mono for _ in range(channels)]
            else:
                samples = pcm.decode(self.artifacts.path_for(t["artifact_id"]), rate, channels)
            off = round(t.get("offset_s", 0.0) * rate) * channels
            if off < 0 or off >= len(out):
                raise ContractError("invalid_track_offset", "offset_s")
            if len(samples)+off > len(out):
                if not t.get("trim_to_allocation", False) or t["kind"] == "speech":
                    raise ContractError("track_exceeds_allocation", "duration")
                samples = samples[:len(out)-off]
            gain = t.get("gain_db", prof["speech_gain_db"] if t["kind"] == "speech" else prof["music_gain_db"])
            factor = 10 ** (gain/20)
            for i, sample in enumerate(samples):
                at = (i+off)/channels/rate
                ducking = (10 ** (-abs(duck.get("amount_db",0))/20)
                           if t["kind"] == "music" and any(
                               r.get("start_frame",r.get("start",0))/fps <= at < r.get("end_frame",r.get("end",0))/fps
                               for r in regions) else 1)
                out[off+i] += sample * factor * ducking
        measured = pcm.measure(out, rate*channels)
        adjustments = {}
        target = prof.get("loudness_target") or {}
        if target and "rms_dbfs" not in target:
            raise ContractError("unsupported_loudness_target", "profile")
        if "rms_dbfs" in target:
            if measured["rms_dbfs"] is None:
                raise ContractError("silent_mix", "loudness")
            delta = target["rms_dbfs"] - measured["rms_dbfs"]
            out = [v*10**(delta/20) for v in out]
            adjustments["loudness_adjustment_db"] = delta
        peak = max((abs(v) for v in out), default=0)
        ceiling = 32768 * 10**(-1/20)
        if peak > ceiling:
            if prof["clip_policy"] != "prevent":
                raise ContractError("mix_clipping", "audio")
            import math
            adjustment = 20*math.log10(peak/ceiling)
            out = [v*ceiling/peak for v in out]
            adjustments["repaired_db"] = round(adjustment,4)
        out = [round(v) for v in out]
        measured = {**pcm.measure(out, rate*channels), **adjustments}
        if "rms_dbfs" in target and abs(measured["rms_dbfs"]-target["rms_dbfs"]) > target.get("tolerance_db",.25):
            raise ContractError("loudness_target_unmet", "mix", "peak headroom conflicts with frozen target")
        # Interleaved samples are already in the target channel layout.
        import io, wave, struct
        stream = io.BytesIO()
        with wave.open(stream,"wb") as wavfile:
            wavfile.setnchannels(channels); wavfile.setsampwidth(2); wavfile.setframerate(rate)
            wavfile.writeframes(struct.pack(f"<{len(out)}h",*out))
        wav = stream.getvalue()
        clipped = measured["clipped"]
        result = {"profile_hash": prof["profile_hash"],
                  "measured": measured, "clipped": clipped,
                  "exact_samples": frames,
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
        envelope=[]
        if duck.get("enabled",False):
            for r in duck.get("regions",[]):
                start=max(region["start_frame"],r.get("start_frame",r.get("start",0)))
                end=min(region["end_frame"],r.get("end_frame",r.get("end",0)))
                if end>start:
                    envelope.append({"start_frame":start,"end_frame":end,"db":-abs(duck.get("amount_db",0))})
        return {"music_gain_db":prof["music_gain_db"],"speech_gain_db":prof["speech_gain_db"],
                "duck_envelope":envelope,"duck_fps":duck.get("fps",30),"sample_rate":prof["sample_rate"],
                "channels":prof["channels"],"loudness_target":prof["loudness_target"],"clip_policy":prof["clip_policy"]}

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
