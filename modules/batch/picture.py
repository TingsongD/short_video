"""Conservative local picture timing from inspected, paired speech evidence."""
import bisect
from pathlib import Path

from .local import Local, probe
from .state import Pause, digest, read, write


def interpolate(points, t):
    index = max(0, min(len(points) - 2, bisect.bisect_right([p[0] for p in points], t) - 1))
    a, b = points[index:index + 2]
    return a[1] + (t - a[0]) * (b[1] - a[1]) / (b[0] - a[0])


def timing_points(pairs, target, native):
    if len(pairs) < 8:
        raise Pause("Too few independently observed speech anchors")
    points = [[(p["reference_start"] + p["reference_end"]) / 2,
               (p["generated_start"] + p["generated_end"]) / 2] for p in pairs]
    points = [p for p in points if 0 < p[0] < target and 0 < p[1] < native]
    if len(points) < 8 or any(b[0] <= a[0] or b[1] <= a[1] for a, b in zip(points, points[1:])):
        raise Pause("Speech timing anchors are not monotonic")
    # Remove local ASR timestamp noise, retaining meaningful phrase drift.
    changed = True
    while changed and len(points) > 3:
        changed = False
        for i in range(1, len(points) - 1):
            if abs(interpolate([points[i-1], points[i+1]], points[i][0]) - points[i][1]) < .04:
                points.pop(i)
                changed = True
                break
    start = max(0., points[0][1] - points[0][0])
    finish = min(native - 1 / 60, target + points[-1][1] - points[-1][0])
    points = [[0., start], *points, [target, finish]]
    for a, b in zip(points, points[1:]):
        if b[0] <= a[0] or b[1] <= a[1] or not .65 <= (b[1]-a[1])/(b[0]-a[0]) <= 1.6:
            raise Pause("Picture timing correction would require an excessive or reversed speed change")
    return points


def selected_picture(v, folder, key):
    job = v["jobs"][key]
    edit = v.get("picture_edits", {}).get(key)
    if not edit:
        return Path(folder) / job["file"]
    source = Path(folder) / job["file"]
    output = Path(folder) / edit["file"]
    speech = Path(folder) / edit["speech_file"]
    if (not source.exists() or digest(source) != edit["source_sha256"]
            or not output.exists() or digest(output) != edit["sha256"]
            or not speech.exists() or digest(speech) != edit["speech_sha256"]):
        raise Pause("Local picture edit is stale or corrupt; inspect its source and narration")
    return output


def fit_picture(batch, number, key, comparison_file):
    if number != batch.active_number():
        raise Pause("Only the active video's picture may be corrected")
    v, folder = batch.video(number), batch.directory(number)
    if v.get("final_path"):
        raise Pause("A finished export needs an intentional new version before changing its picture")
    job = v["jobs"][key]
    if job["kind"] != "video" or job["stage"] != "downloaded":
        raise Pause("Picture correction needs a completed video")
    report = read(comparison_file)
    if not report.get("same_transcript"):
        raise Pause("Timing correction cannot repair omitted or changed speech")
    brief = read(folder / "brief.json")
    take_key = job.get("replacement_for", key)
    take = next(t for t in brief["takes"] if t["id"] == take_key)
    frames = take["end_frame"] - take["start_frame"]
    source = folder / job["file"]
    if digest(source) != job["sha256"]:
        raise Pause("Original generated clip changed")
    speech = folder / "audio" / (take_key + ".wav")
    local = Local(folder)
    info = probe(local, source)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    points = timing_points(report["pairs"], frames / 30, float(stream["duration"]))
    start, finish = points[0][1], points[-1][1]
    expression = ""
    for a, b in reversed(list(zip(points, points[1:]))):
        piece = f"({a[0]:.9f}+(T+{start:.9f}-{a[1]:.9f})*{(b[0]-a[0])/(b[1]-a[1]):.9f})"
        expression = piece if not expression else f"if(lt(T+{start:.9f},{b[1]:.9f}),{piece},{expression})"
    output = folder / "assets/aligned" / (key + ".mp4")
    output.parent.mkdir(exist_ok=True)
    temp = output.with_name(key + ".pending.mp4")
    vf = (f"trim=start={start:.9f}:end={finish:.9f},setpts=PTS-STARTPTS,setpts='{expression}/TB',"
          f"fps=30,tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={frames},setpts=N/(30*TB)")
    local.run(["ffmpeg", "-v", "error", "-y", "-i", source, "-an", "-vf", vf,
               "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-movflags", "+faststart", temp])
    check = next(s for s in probe(local, temp)["streams"] if s["codec_type"] == "video")
    if int(check["nb_frames"]) != frames or check["avg_frame_rate"] != "30/1":
        raise Pause("Corrected picture frame count/rate failed")
    temp.replace(output)
    residuals = [abs(interpolate(points, (p["reference_start"]+p["reference_end"])/2)
                     - (p["generated_start"]+p["generated_end"])/2) for p in report["pairs"]]
    edit = {"file": str(output.relative_to(folder)), "sha256": digest(output), "source_sha256": digest(source),
            "speech_file": str(speech.relative_to(folder)), "speech_sha256": digest(speech),
            "frames": frames, "target_to_source_anchors": points, "comparison_file": str(Path(comparison_file).resolve()),
            "max_anchor_residual_s": max(residuals), "method": "Local monotonic picture retiming; original speech unchanged",
            "limits": "ASR anchors approximate timing; direct visual inspection remains required."}
    v.setdefault("picture_edits", {})[key] = edit
    v.setdefault("reviews", {}).pop(key, None)
    batch.save()
    write(output.with_suffix(".json"), edit)
    return edit
