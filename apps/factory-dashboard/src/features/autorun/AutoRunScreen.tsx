import React, { useMemo, useState } from "react";
import { api, call } from "../../api/client";

type Row = Record<string, any>;

const STAGES: [string, string][] = [
  ["intake", "Seed intake"], ["evidence", "Reference evidence"],
  ["video_analysis", "Video analysis"], ["sections", "Analysis write-up"],
  ["analysis_review", "Analysis review"], ["blueprint", "Blueprint"],
  ["template", "Format template"], ["script", "Script adaptation"],
  ["music", "Music"], ["draft", "Experiment draft"],
  ["tts", "Narration"], ["quote", "Footage quote"],
  ["authorize", "Authorization"], ["run", "Dispatch"],
  ["footage", "Footage generation"], ["compose", "Rendering"],
  ["final_qc", "Final quality check"], ["done", "Complete"],
];
const LABEL = Object.fromEntries(STAGES);

function StageBar({ run }: { run: Row }) {
  const done = new Set(
    (run.progress || [])
      .filter((p: Row) => p.outcome === "done")
      .map((p: Row) => p.stage));
  return (
    <ol className="stage-bar" aria-label="pipeline progress">
      {STAGES.map(([key, label]) => (
        <li key={key}
            className={done.has(key) ? "done"
                       : key === run.stage && run.status === "running"
                         ? "current" : key === run.stage ? "at" : ""}
            aria-current={key === run.stage ? "step" : undefined}>
          {label}
        </li>
      ))}
    </ol>
  );
}

export function AutoRunScreen({ seeds, budgets, runs, act, media,
                                onSelectExperiment }: {
  seeds: Row[]; budgets: Row[]; runs: Row[];
  act: (fn: () => Promise<unknown>, message?: string) => Promise<unknown>;
  media: (id: string) => string;
  onSelectExperiment: (id: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [seedId, setSeedId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [language, setLanguage] = useState("en");
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [limits, setLimits] = useState<Record<string, string>>({});
  const [music, setMusic] = useState(false);
  const [reviews, setReviews] = useState(true);
  const [account, setAccount] = useState("");
  const [reviewer, setReviewer] = useState("");
  const seed = seeds.find((s) => s.id === seedId);
  const units = useMemo(
    () => [...new Set(budgets.map((b) => b.unit))] as string[], [budgets]);
  const selectedBudgets = budgets.filter((b) => picked[b.id]);

  async function importAndAttach(file: File) {
    const r = await api.importFile(file) as Row;
    await call("POST", `/api/seeds/${seedId}/media`,
               { body: { artifact_id: r.artifact.id } });
  }

  function launch() {
    const lim = Object.fromEntries(
      Object.entries(limits)
        .filter(([, v]) => v.trim() !== "")
        .map(([k, v]) => [k, Number(v)]));
    return api.autorunCreate({
      seed_id: seedId, voice_id: voiceId, language,
      budget_ids: selectedBudgets.map((b) => b.id),
      limits: lim, generate_music: music, visual_reviews: reviews,
      account: account || undefined,
    });
  }

  const ready = seed && seed.evidence_status === "media_ready" &&
    voiceId.trim() && selectedBudgets.length > 0;

  return (
    <section>
      <h2>Automatic seed → A–D</h2>
      <p>One action runs analysis, script adaptation, narration,
         captions, footage, automated checks and rendering. It pauses
         only for a missing choice, exhausted spend authority, or a
         problem that needs a person. Publishing stays a separate
         decision.</p>

      <fieldset>
        <legend>1 · Source video</legend>
        <label>Seed video link
          <input value={url} onChange={(e) => setUrl(e.target.value)}
                 placeholder="https://…" /></label>
        <button onClick={() => act(async () => {
          const r = await api.createSeed(url) as Row;
          setSeedId(r.seed.seed.id);
        }, "Seed registered — import its media next")}>Add source</button>
        <label>Or pick an existing seed
          <select value={seedId} onChange={(e) => setSeedId(e.target.value)}>
            <option value="">Select a seed</option>
            {seeds.map((s) => (
              <option key={s.id} value={s.id}>
                {s.id} · {s.evidence_status}</option>))}
          </select></label>
        {seed && seed.evidence_status !== "media_ready" && (
          <label>Source media file
            <input type="file" accept="video/*"
                   onChange={(e) => {
                     const f = e.target.files?.[0];
                     if (f) act(() => importAndAttach(f),
                                "Source media attached");
                   }} /></label>)}
        {seed && seed.evidence_status === "media_ready" &&
          seed.source_asset_id && (
          <video controls src={media(seed.source_asset_id)}
                 style={{ maxHeight: 160 }} />)}
      </fieldset>

      <fieldset>
        <legend>2 · Voice and spend authority</legend>
        <label>TTS voice id
          <input value={voiceId}
                 onChange={(e) => setVoiceId(e.target.value)}
                 placeholder="provider voice id (eleven_v3)" /></label>
        <label>Language
          <input value={language}
                 onChange={(e) => setLanguage(e.target.value)} /></label>
        <fieldset>
          <legend>Budgets this run may draw from</legend>
          {budgets.map((b) => (
            <label key={b.id}>
              <input type="checkbox" checked={!!picked[b.id]}
                     onChange={(e) => setPicked(
                       { ...picked, [b.id]: e.target.checked })} />
              {b.id} · {b.unit} · available {String(b.available)}
              {b.retired ? " (retired)" : ""}
            </label>))}
          {!budgets.length && <p>No budgets yet — create one in the
            Budgets tab first.</p>}
        </fieldset>
        <fieldset>
          <legend>Optional per-operation limits</legend>
          {units.map((u) => (
            <label key={u}>{u} limit
              <input value={limits[u] || ""} inputMode="numeric"
                     placeholder="largest single operation"
                     onChange={(e) => setLimits(
                       { ...limits, [u]: e.target.value })} /></label>))}
        </fieldset>
        <label>Provider account
          <input value={account}
                 onChange={(e) => setAccount(e.target.value)}
                 placeholder="generation account (if required)" /></label>
        <label>
          <input type="checkbox" checked={music}
                 onChange={(e) => setMusic(e.target.checked)} />
          Generate an instrumental music bed (spends music credits)
        </label>
        <label>
          <input type="checkbox" checked={reviews}
                 onChange={(e) => setReviews(e.target.checked)} />
          Automated final visual QC (spends analysis budget)
        </label>
      </fieldset>

      <button disabled={!ready}
              onClick={() => act(launch,
                "Automatic run started — watch progress below")}>
        Generate A–D automatically</button>
      {!ready && <p className="hint">Needs a seed with media, a voice id,
        and at least one budget.</p>}

      <h3>Runs</h3>
      {runs.map((run) => (
        <article key={run.id} className={`run ${run.status}`}>
          <header>
            <strong>{run.id}</strong> · {run.status}
            {run.experiment_id && (
              <button onClick={() => onSelectExperiment(
                run.experiment_id)}>
                Open {run.experiment_id} in Compare</button>)}
          </header>
          <StageBar run={run} />
          {run.status === "paused" && run.pause && (
            <div className="pause" role="alert">
              <strong>{run.pause.code}</strong>
              <p>{run.pause.detail}</p>
              <p><em>{run.pause.action}</em></p>
              {run.pause.code === "budget_exhausted" && (
                <p className="hint">The message names the ceiling that
                  blocks. Raise it in the Budgets tab (same id, higher
                  amount) or settle finished holds there, then Resume.
                  Every aggregate ceiling is held in full, so adding a
                  second aggregate budget does not add headroom.</p>)}
              {run.pause.code === "final_qc_blocked" && (
                <p className="hint">A final on disk is not validation —
                  every mandatory check must pass on the current bytes.
                  The failing checks are named above; inspect them in
                  Compare, fix the cause, then Resume.</p>)}
              {run.pause.code === "final_qc_flagged" && (
                <p>
                  <label>Reviewer
                    <input value={reviewer} placeholder="your name"
                           onChange={(e) =>
                             setReviewer(e.target.value)} /></label>{" "}
                  <button disabled={!reviewer.trim()}
                          onClick={() => act(
                    () => api.autorunResume(run.id,
                      { resolve_qc: "accept",
                        reviewer: reviewer.trim() }),
                    "Flagged finals accepted")}>
                    Accept after human review</button>{" "}
                  <button onClick={() => act(
                    () => api.autorunResume(run.id,
                      { resolve_qc: "recheck" }),
                    "Flagged finals resubmitted for review")}>
                    Recheck once</button>
                </p>)}
              {run.pause.code === "capability_unavailable" && (
                <p>
                  {run.stage === "final_qc" && (
                    <button onClick={() => act(
                      () => api.autorunResume(run.id,
                        { set_params: { visual_reviews: false } }),
                      "Run finishing on technical checks only")}>
                      Finish on technical checks only</button>)}
                  {run.stage === "music" && (
                    <button onClick={() => act(
                      () => api.autorunResume(run.id,
                        { set_params: { generate_music: false } }),
                      "Run continuing without music")}>
                      Finish without music</button>)}
                </p>)}
              <button onClick={() => act(
                () => api.autorunResume(run.id,
                  selectedBudgets.length
                    ? { add_budget_ids: selectedBudgets.map((b) => b.id) }
                    : {}),
                "Run resumed")}>
                Resume{selectedBudgets.length
                  ? " with checked budgets" : ""}</button>
            </div>)}
          {(run.progress || []).some(
            (p: Row) => p.outcome === "paused" && p.detail) && (
            <details><summary>Pause history</summary>
              <ul>{(run.progress || [])
                .filter((p: Row) => p.outcome === "paused" && p.detail)
                .map((p: Row, i: number) => (
                  <li key={i}><strong>{p.code}</strong> ({p.stage},{" "}
                    {String(p.at).slice(0, 16)}) — {p.detail}
                    {p.action && <em> · {p.action}</em>}</li>))}
              </ul></details>)}
          {(run.notes || []).length > 0 && (
            <details><summary>Limitations</summary>
              <ul>{run.notes.map((n: string, i: number) => (
                <li key={i}>{n}</li>))}</ul></details>)}
        </article>))}
      {!runs.length && <p>No automatic runs yet.</p>}
    </section>
  );
}
