"""Hypit captions and picture, one section at a time; FFmpeg joins continuous audio."""
import re
import shutil
import time
from pathlib import Path

from modules.assemble.hypit_markup import escape_markup_text as esc
from .local import probe, verify_media
from .picture import selected_picture
from .state import Pause, digest, now, read, write

ROOT = Path(__file__).resolve().parents[2]
HYPIT = ROOT / "scripts/hypit.sh"


def cues(words, frames=5091):
    groups, group, result = [], [], []
    for word in words:
        group.append(word)
        if len(group) == 6 or re.search(r"[.!?]$", word["text"]):
            groups.append(group)
            group = []
    if group:
        groups.append(group)
    for gi, group in enumerate(groups):
        for wi, word in enumerate(group):
            following = (group[wi + 1]["start"] if wi + 1 < len(group) else
                         groups[gi + 1][0]["start"] if gi + 1 < len(groups) else word["end"] + .12)
            start = max(43, round(word["start"] * 30))
            # Same-frame words share the later, complete progressive caption;
            # forcing an earlier prefix to last a frame stacks text on itself.
            end = min(frames, round(following * 30))
            if end > start and word["end"] > 43 / 30:
                result.append({"start": start, "end": end,
                               "text": " ".join(w["text"] for w in group[:wi + 1])})
    return result


def author(folder, brief, v, selected=None):
    frames = brief.get("timeline_frames", 5091)
    takes = brief["takes"] if selected is None else [selected]
    name = "final" if selected is None else "export-" + selected["id"]
    lines = ['<?svml using="@hypit/markup@1"?>', '<svml>']
    for short, package in [("asset", "media"), ("time", "timeline-author"), ("space", "spatial"),
                           ("pipeline", "media-pipeline"), ("media", "media-track"), ("audio", "audio-track"),
                           ("typo", "typography-track"), ("film", "film"), ("render", "render-hyperframes")]:
        lines.append(f'<import as="{short}" from="@hypit/{package}@1"/>')
    lines += ['<import as="look" source="./style.svs"/>', '<time:Clock id="clock" frame-rate="30"/>',
              f'<time:Timeline id="program" clock={{clock}} end="{frames}f"/>', '<space:Canvas id="canvas" width="1080" height="1920"/>']
    for key, l, t, r, b in [("full", 0, 0, 100, 100), ("caption-frame", 8, 68, 92, 76),
                           ("label-frame", 8, 76, 92, 82), ("headline-frame", 9, 49, 96, 59)]:
        lines.append(f'<space:Frame id="{key}" within={{canvas}} left="{l}%" top="{t}%" right="{r}%" bottom="{b}%"/>')
    for key in ("caption", "label", "headline"):
        lines.append(f'<asset:Font id="{key}-font" src="./assets/{key}.ttf" weight="400" style="{"italic" if key == "label" else "normal"}"/>')
        lines.append(f'<typo:Style id="{key}-style" recipe={{look.text.{key}}} font={{{key}-font}}><typo:Shadow color="#000000dd" x="0" y="2" blur="4"/><typo:Fill color="#ffffff"/></typo:Style>')
    for take in takes:
        key = take["id"]
        file = selected_picture(v, folder, v.get("selected_jobs", {}).get(key, key)).relative_to(folder)
        lines += [f'<asset:Video id="{key}-file" src="./{esc(str(file))}"/>',
                  f'<pipeline:Normalize id="{key}" source={{{key}-file}} clock={{clock}} video="primary-moving" audio="none" span-authority="video"/>']
    lines.append('<media:Track id="footage" timeline={program.timeline} canvas={canvas}>')
    for take in takes:
        lines.append(f'<media:Item id="picture-{take["id"]}" media={{{take["id"]}.media}} frame={{full}} start="{take["start_frame"]}f" end="{take["end_frame"]}f" appearance={{look.media.full}}/>')
    lines += ['</media:Track>', '<typo:Track id="titles" timeline={program.timeline}>']
    start, stop = (0, frames) if selected is None else (selected["start_frame"], selected["end_frame"])
    for index, cue in enumerate(cues(read(folder / "audio/words.json"), frames)):
        if cue["start"] < stop and cue["end"] > start:
            lines.append(f'<typo:Area id="caption-{index}" placement={{caption-frame}} style={{caption-style}} start="{cue["start"]}f" end="{cue["end"]}f">{esc(cue["text"])}</typo:Area>')
    for product in brief["products"]:
        a = next(t["start_frame"] for t in brief["takes"] if t["slot"] == product["slot"]) + 14
        b = a + 70
        if a < stop and b > start:
            lines.append(f'<typo:Area id="label-{product["slot"]}" placement={{label-frame}} style={{label-style}} start="{a}f" end="{b}f">{esc(product["label"])}</typo:Area>')
    if start == 0:
        for index, (a, b, text) in enumerate([(0, 3, "|"), (3, 6, "MS|"), (6, 9, "MSDR|"), (9, 12, "MSDRESS|"), (12, 16, "MSDRESSLY|"), (16, 43, "MSDRESSLY")]):
            lines.append(f'<typo:Area id="brand-{index}" placement={{headline-frame}} style={{headline-style}} start="{a}f" end="{b}f">{text}</typo:Area>')
    lines.append('</typo:Track>')
    if selected is None:
        for audio_name in ("narration", "music-bed"):
            lines += [f'<asset:Audio id="{audio_name}-file" src="./audio/{audio_name}.wav"/>',
                f'<pipeline:Normalize id="{audio_name}" source={{{audio_name}-file}} clock={{clock}} video="none" audio="default" span-authority="audio"/>',
                f'<audio:Track id="{audio_name}-track" timeline={{program.timeline}}><audio:Item id="{audio_name}-sound" source={{{audio_name}.media}} start="0f" end="{frames}f" gain="{1.25 if audio_name == "narration" else 1}"/></audio:Track>']
    lines += ['<film:Film id="main" canvas={canvas} timeline={program.timeline} appearance={look.film.main}>',
              '<film:Track source={footage.visual}/><film:Track source={titles.track}/>']
    if selected is None:
        lines += ['<film:Track source={narration-track.audio}/><film:Track source={music-bed-track.audio}/>']
    lines += ['</film:Film>', f'<render:Video id="final" start-frame="{start}" end-frame-exclusive="{stop}" composition={{main.composition}} timeline={{program.timeline}}/>', '</svml>']
    (folder / (name + ".svml")).write_text("\n".join(lines) + "\n")
    (folder / (name + ".svrun")).write_text('<?svml using="@hypit/run-markup@1"?>\n<svrun version="1"><author source="./' + name + '.svml"/><target output="final.video"/></svrun>\n')
    return name


def join_sections(local, paths, takes, narration, music, final):
    playlist = paths[0].parent / "concat.txt"
    # MP4 container durations are rounded; use the accepted frame counts to
    # place each section, and retain zero-based picture timestamps despite AAC priming.
    playlist.write_text("".join(
        f"file '{path.name}'\nduration {(take['end_frame'] - take['start_frame']) / 30:.12f}\n"
        for path, take in zip(paths, takes, strict=True)))
    duration = sum(t["end_frame"] - t["start_frame"] for t in takes) / 30
    local.run(["ffmpeg", "-v", "error", "-y", "-copyts", "-f", "concat", "-safe", "0", "-i", playlist,
        "-i", narration, "-i", music,
        "-filter_complex", "[1:a]volume=1.25[voice];[voice][2:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", str(duration),
        "-movflags", "+faststart", final], timeout=300)


class Render:
    def __init__(self, batch, number, local, previous):
        self.batch, self.number, self.local, self.previous = batch, number, local, Path(previous)
        self.v, self.folder = batch.video(number), batch.directory(number)

    def call(self, *args, timeout=180):
        return self.local.run([HYPIT, *args, "--json"], timeout=timeout, json_output=True)

    def setup(self):
        write(self.folder / "package.json", {"name": f"msdressly-batch-haul-{self.number:02}", "private": True, "type": "module"})
        for font in ("caption", "label", "headline"):
            shutil.copy2(self.previous / "assets" / (font + ".ttf"), self.folder / "assets" / (font + ".ttf"))
        # Two-line product names fit inside the established lower-third frame.
        style = (self.previous / "style.svs").read_text().replace("text.label { size: 63;", "text.label { size: 48;")
        (self.folder / "style.svs").write_text(style)
        write(self.folder / "hypit.runtime.json", {"format": "hypit.runtime-local@1", "dataRoot": ".hypit/runtimes/local",
            "endpoints": {"media.local": {"use": "@hypit/provider-media-local", "config": {"defaultConcurrency": 1}},
            "hyperframes.local": {"use": "@hypit/provider-hyperframes-local", "config": {"workers": 1, "defaultConcurrency": 1, "browserCapacity": 1}}}})
        self.call("runtime", "use", "hypit.runtime.json")
        self.call("runtime", "up", "--runtime", "hypit.runtime.json", "--endpoint", "media.local", "--endpoint", "hyperframes.local")

    def finish(self, brief):
        if (self.batch.data.get("execution", {}).get("render_backend") == "ffmpeg"
                and not list((self.folder / "rendered-sections").glob("clip-*.json"))):
            from .fast_render import FastRender
            return FastRender(self.batch, self.number, self.local, self.previous).finish(brief)
        self.setup()
        sections = self.folder / "rendered-sections"
        sections.mkdir(exist_ok=True)
        author(self.folder, brief, self.v)
        paths = []
        for take in brief["takes"]:
            key = take["id"]
            file, receipt = sections / (key + ".mp4"), sections / (key + ".json")
            doc = read(receipt) if receipt.exists() else {}
            name = author(self.folder, brief, self.v, take)
            inputs = {"author": digest(self.folder / (name + ".svml")), "style": digest(self.folder / "style.svs"),
                      "picture": digest(selected_picture(self.v, self.folder, self.v.get("selected_jobs", {}).get(key, key)))}
            if doc and doc.get("inputs") != inputs:
                raise Pause("Rendered section inputs changed; preserve its existing build and prepare an intentional local revision")
            if doc.get("state") == "verified" and file.exists() and digest(file) == doc["sha256"]:
                paths.append(file)
                continue
            if not doc:
                checked = self.call("check", name + ".svrun")
                plan = self.call("plan", name + ".svrun", "--runtime", "hypit.runtime.json")
                if not checked.get("ok") or not plan.get("ok") or plan["providerRequestCount"] or plan["unresolvedRequestCount"]:
                    raise Pause("Hypit validation failed or would request an unapproved paid provider")
                doc = {"state": "building", "source": name, "started_at": now(), "inputs": inputs}
                write(receipt, doc)
                build = self.call("build", name + ".svrun", "--runtime", "hypit.runtime.json")
                doc["build_id"] = build["build"]["id"]
                write(receipt, doc)
            if not doc.get("build_id"):
                raise Pause("Render submission response lost; reconcile Hypit build history before retrying")
            while True:
                state = self.call("status", doc["build_id"], "--runtime", "hypit.runtime.json")["build"]
                if state["work"]["state"] == "done":
                    if state["work"].get("outcome") != "complete":
                        raise Pause("Hypit render failed; inspect saved build logs")
                    break
                print(f"Rendering {key}", flush=True)
                time.sleep(10)
            self.call("get", doc["build_id"], "--output", "final.video", "--to", file)
            info = probe(self.local, file)
            stream = next(s for s in info["streams"] if s["codec_type"] == "video")
            if int(stream["nb_frames"]) != take["end_frame"] - take["start_frame"] or stream["avg_frame_rate"] != "30/1":
                raise Pause("Rendered section frame count or rate differs from timeline")
            doc.update(state="verified", sha256=digest(file))
            write(receipt, doc)
            paths.append(file)
        name = brief["delivery_name"]
        final = self.folder / name
        join_sections(self.local, paths, brief["takes"], self.folder / "audio/narration.wav",
                      self.folder / "audio/music-bed.wav", final)
        report = verify_media(self.local, final, "video", brief.get("timeline_frames", 5091) / 30, final=True)
        self.v.update(state="rendered", final_path=str(final), technical_qc=report)
        write(self.folder / "technical-qc.json", report)
        self.batch.save()
        return final
