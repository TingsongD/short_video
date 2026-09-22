import React, { useMemo, useState } from "react";
import { api, call } from "../../api/client";
import { selectableBudget } from '../../api/budgets';
import { credentialRecovery, analysisRecovery } from "../providers/recovery";
import { RecoveryPanel } from './RecoveryPanel';

type Row = Record<string, any>;

const STAGES: [string, string][] = [
  ["intake", "Seed intake"], ["evidence", "Reference evidence"],
  ["video_analysis", "Video analysis"], ["sections", "Analysis write-up"],
  ["analysis_review", "Analysis checks"], ["blueprint", "Blueprint"],
  ["template", "Format template"], ["script", "Script adaptation"],
  ["music", "Music"], ["draft", "Experiment draft"],
  ["tts", "Narration"], ["quote", "Footage quote"],
  ["authorize", "Authorization"], ["run", "Dispatch"],
  ["footage", "Footage generation"], ["compose", "Rendering"],
  ["final_qc", "Final quality check"], ["done", "Complete"],
];
const LABEL = Object.fromEntries(STAGES);

export function RunProgress({ run }: { run: Row }) {
  const stages = STAGES.filter(([key]) => key !== "done");
  const current = stages.findIndex(([key]) => key === run.stage);
  // Historical completed events survive rewinds; don't count stages ahead
  // of the current stage as completed work in the current execution.
  const done = new Set((run.progress || []).filter((p: Row) =>
    p.outcome === "done").map((p: Row) => p.stage));
  const complete = run.status === "succeeded";
  const count = complete ? stages.length : stages.filter(([key], i) =>
    i < current && done.has(key)).length;
  const percent = Math.round(count / stages.length * 100);
  const state = complete ? "Run complete" : run.status === "paused"
    ? "Paused — needs attention" : run.status === "running" ? "Running" : run.status;
  const phases = run.state?.completion_phases || {};
  const deliveryPhase = phases.delivery === 'running' && run.status === 'paused' ? 'paused'
    : phases.delivery || (complete && run.params?.policies?.delivery === 'creative_approval' ? 'awaiting creative approval' : 'pending');
  const narrationRepairs = Object.entries(run.state?.speech_repair_attempts || {});
  const overlayRepairs = Object.entries(run.state?.overlay_repair_attempts || {});
  const source=run.source_analysis;
  const spend=run.spending_policy;
  return <div className={`run-progress ${run.status}`}>
    <div role="status" aria-live="polite">
      <strong>{state}</strong> · {LABEL[run.stage] || run.stage}
      <span className="progress-count">{count}/{stages.length} stages · {percent}%</span>
    </div>
    <progress aria-label={`Run progress ${run.id}`} max={stages.length} value={count}
      aria-valuetext={`${count} of ${stages.length} stages completed; ${state}; ${LABEL[run.stage] || run.stage}`} />
    <small>Stage completion, not a time estimate. Generation stages may take longer.</small>
    {spend && <p aria-label="Run USD guardrail">
      ${(Number(spend.remaining || 0) / 1_000_000).toFixed(2)} remaining of ${(Number(spend.cap_amount || 0) / 1_000_000).toFixed(2)} cumulative USD; holds and confirmed usage both count. This guardrail belongs only to this run.
    </p>}
    {source && <section aria-label="Source analysis details">
      <h4>Source analysis · {String(source.stage || 'waiting').replace(/_/g,' ')}</h4>
      <p>{source.state === 'complete' ? 'Source evidence and interpretation complete.' : source.state === 'waiting' ? 'Waiting — existing work is preserved.' : source.state === 'paused' ? 'Source analysis paused.' : 'Measuring source evidence.'}</p>
      <p>{source.encoded_frames ?? 0} frames encoded · {source.decoded_frames ?? 'unknown'} decoded</p>
      {Number.isInteger(source.total_frames) && source.total_frames > 0
        ? <progress aria-label="Source frame coverage" max={source.total_frames} value={source.encoded_frames ?? 0}/>
        : <p>Total frame count not yet verified — no estimated percentage.</p>}
      <p>Audio: {source.audio_status || 'pending'} · {((source.processed_audio_samples ?? 0)/48000).toFixed(1)} seconds processed · Rhythm: {source.rhythm_status || 'pending'}</p>
      <p>Measured events: {source.event_count ?? 'pending'} · Cached chunks reused: {source.cache_reused_chunks ?? 0}</p>
      <p>Local repairs: {source.repairs_used ?? 0} (at most two per chunk) · Clarifications: {source.clarifications_used ?? 0}/2</p>
      <p>Jev {source.jev_mode || 'shadow'}: {source.jev_status || 'pending'} — mandatory evidence is retained.</p>
      {source.jev_status === 'unknown_retained' && <p>Unknown Jev outcome retained for reconciliation; no request replay or hold release.</p>}
      {source.next_attempt_at && <p>Next attempt: {source.next_attempt_at}</p>}
      {source.updated_at && <p>Evidence last updated: {source.updated_at}</p>}
    </section>}
    {run.status === 'running' && run.state?.provider_wait?.reason === 'analysis_throttled' &&
      <p role="status">Google is busy — waiting before an automatic QC/analysis retry. Up to two retries; existing clips are preserved.</p>}
    {run.state?.source_timing && <details><summary>Source timing evidence</summary>
      <ul>{(run.state.source_timing.passages||[]).map((p:Row,i:number)=><li key={i}>Passage {i+1}: {p.quality === 'passage_only' ? 'Passage timing only — word timing unavailable' : p.quality} · {p.attempts}/2 local repair attempts</li>)}</ul>
      <p>Final captions use replacement narration alignment, not source-word estimates.</p>
    </details>}
    {run.params?.policies && <>
      <p aria-label="Completion phases">Generation: {phases.generation || (complete || run.stage === 'final_qc' ? 'complete' : 'in progress')} · QC: {phases.qc || (complete ? 'complete' : run.stage === 'final_qc' ? 'in progress' : 'pending')} · Delivery: {deliveryPhase}</p>
      <p>{run.params.policies.variation === 'full_video' ? 'Full-video multi-variable creative comparison' : 'Controlled-region comparison'} · {run.params.policies.captions === 'phrases.v1' ? 'Readable phrase captions' : 'Word captions'}</p>
      {(narrationRepairs.length > 0 || overlayRepairs.length > 0) && <details><summary>Automatic repair progress</summary>
        <ul>{narrationRepairs.map(([key, used]) => <li key={key}>Narration {key}: {String(used)}/{run.params.policies.speech_repairs} attempts</li>)}
        {overlayRepairs.map(([key, used]) => <li key={key}>{run.state?.overlay_repair_labels?.[key] || `Clip ${key}`}: {String(used)}/{run.params.policies.overlay_repairs} attempts</li>)}</ul>
        <p>Attempts persist across restarts. Unknown provider outcomes pause without resubmission.</p>
      </details>}
    </>}
    {run.status === "paused" && <p className="progress-problem">
      {run.recovery ? <>{run.recovery.title}<br/>{run.recovery.message}</>
        : <>{run.pause?.code}: {run.pause?.detail}<br />{credentialRecovery(run.pause?.detail) || analysisRecovery(run.pause?.detail) || run.pause?.action}</>}
    </p>}
    {complete && <p className="hint">{phases.delivery === 'complete' ? 'Finals verified on Drive. Nothing published; creative approval is separate.' : 'Open Compare to review results. Completion does not mean published or delivered.'}</p>}
  </div>;
}

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

export function AutoRunScreen({ seeds, budgets: allBudgets, runs, act, media,
                                onSelectExperiment }: {
  seeds: Row[]; budgets: Row[]; runs: Row[];
  act: (fn: () => Promise<unknown>, message?: string) => Promise<unknown>;
  media: (id: string) => string;
  onSelectExperiment: (id: string) => void;
}) {
  const budgets = useMemo(() => allBudgets.filter(selectableBudget), [allBudgets]);
  const [url, setUrl] = useState("");
  const [seedId, setSeedId] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [language, setLanguage] = useState("en");
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [limits, setLimits] = useState<Record<string, string>>({});
  const [music, setMusic] = useState(false);
  const [reviews, setReviews] = useState(true);
  const [variation, setVariation] = useState('full_video');
  const [profileId,setProfileId]=useState('legacy');
  const [captions, setCaptions] = useState('phrases.v1');
  const [delivery, setDelivery] = useState('configured');
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
      ...(profileId==='legacy'?{}:{profile_id:profileId}),
      policies: {version: 1, variation, captions, speech_repairs: 2, overlay_repairs: 2,
        ...(delivery === 'configured' ? {} : {delivery})},
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
          <p>New runs receive up to $50 cumulative USD per new run automatically. This run-owned guardrail counts pending holds and confirmed usage and cannot fund unrelated work. Select separate budgets for provider credits or any stricter shared ceilings you want enforced.</p>
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
          <legend>Optional per-plan limits</legend>
          {units.map((u) => (
            <label key={u}>{u} limit
              <input value={limits[u] || ""} inputMode="numeric"
                     placeholder="maximum total for one quoted plan"
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
          <input type="checkbox" checked={reviews} disabled={profileId==='flashcut_hypit.v1'}
                 onChange={(e) => setReviews(e.target.checked)} />
          Automated final visual QC (spends analysis budget)
        </label>
      </fieldset>

      <fieldset><legend>3 · Video policies (frozen for this run)</legend>
        <label>Workflow profile<select value={profileId} onChange={e=>{
          setProfileId(e.target.value);
          if(e.target.value==='flashcut_hypit.v1'){setCaptions('phrases.v1');setReviews(true);}
        }}>
          <option value="legacy">Standard — existing workflow</option>
          <option value="flashcut_hypit.v1">Flash-cut — all-frame PE, audio, Jev and Gemini, native Hypit</option>
        </select></label>
        {profileId==='flashcut_hypit.v1' && <p>Requires the installed local helper and separately qualified analysis routes. Every decoded frame is processed; no publishing or character-reference generation is enabled.</p>}
        <label>Footage variation<select value={variation} onChange={e=>setVariation(e.target.value)}>
          <option value="full_video">Full video — distinct B/C/D footage in every beat</option>
          <option value="controlled_regions">Controlled regions — selected beats only</option>
        </select></label>
        <p>Full-video variants compare multiple creative changes, not isolated causal effects.</p>
        <label>Caption style<select value={captions} disabled={profileId==='flashcut_hypit.v1'} onChange={e=>setCaptions(e.target.value)}>
          <option value="phrases.v1">Readable phrases — large text, at most two lines</option>
          <option value="words.v1">Legacy word captions</option>
        </select></label>
        <label>Drive delivery<select value={delivery} onChange={e=>setDelivery(e.target.value)}>
          <option value="configured">Automatic after QC when an authorized destination is configured</option>
          <option value="creative_approval">Wait for human creative approval</option>
        </select></label>
        <p>At most two narration repairs per segment and two overlay repairs per clip, within selected budgets. Automatic delivery requires final visual QC and verified remote files. Publishing stays disabled.</p>
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
            <strong>{run.id}</strong> · {run.status}{run.archived && ' · Archived'}
            {run.experiment_id && (
              <button onClick={() => onSelectExperiment(
                run.experiment_id)}>
                Open {run.experiment_id} in Compare</button>)}
          </header>
          <RunProgress run={run} />
          <StageBar run={run} />
          {run.status === "paused" && run.pause && (
            <div className="pause" role="alert">
              {run.recovery ? <RecoveryPanel key={`${run.id}:${run.pause.at}`} run={run} act={act}/>
                : <>
              <strong>{run.pause.code}</strong>
              <p>{run.pause.detail}</p>
              <p><em>{credentialRecovery(run.pause.detail) || analysisRecovery(run.pause.detail) || run.pause.action}</em></p>
              </>}
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
              {(!run.recovery || run.recovery.can_resume) && <button onClick={() => act(
                () => api.autorunResume(run.id, {
                  // Bind this click to the current pause so a later
                  // pause cannot replay the first Resume's idempotent
                  // response (empty bodies would otherwise collide).
                  pause_at: run.pause?.at,
                  ...(selectedBudgets.length
                    ? { add_budget_ids: selectedBudgets.map((b) => b.id) }
                    : {}),
                }),
                "Run resumed")}>
                Resume{selectedBudgets.length
                  ? " with checked budgets" : ""}</button>}
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
