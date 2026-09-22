import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { Blocked, Empty, ErrorBox } from "../../components/States";

type Row = Record<string, any>;

const UNDERSTANDING: [string, string][] = [
  ["premise", "Premise — what is this video, in one line?"],
  ["progression", "Progression — how does it build, beat by beat?"],
  ["hook", "Opening hook — what makes the first second work?"],
  ["setups", "Setups — what expectations does it plant?"],
  ["payoffs", "Payoffs — where and how do they land?"],
  ["ending", "Ending — how does it close?"],
  ["replay_appeal", "Replay appeal — why watch again / loop?"],
  ["intended_response", "Intended response — what should the viewer feel or do?"],
];
const TREATMENT: [string, string][] = [
  ["summary", "Treatment summary — the adaptation in one paragraph"],
  ["preserves", "Preserves — which relationships from the source we keep"],
  ["redesigns", "Redesigns — what we change and why"],
  ["script_direction", "Script direction — the new piece's words/actions"],
];
const STAGES = ["acquire", "transcript", "evidence", "documents"];

/** Source evidence editor; automated runs do not require scene approval. */
export function AnalysisScreen({ seeds, blueprints, reviewer, act, media }: {
  seeds: Row[]; blueprints: Row[]; reviewer: string;
  act: (fn: () => Promise<unknown>, message?: string) => Promise<unknown>;
  media: (id: string) => string;
}) {
  const [seedId, setSeed] = useState("");
  const [a, setA] = useState<Row | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [u, setU] = useState<Row>({});
  const [sections, setSections] = useState<Row[]>([]);
  const [t, setT] = useState<Row>({});
  const [note, setNote] = useState("");
  const [tx, setTx] = useState({ provider: "", provenance: "", words: "" });
  const currentSeed = useRef(seedId); currentSeed.current = seedId;
  const serial = useRef(0), dirty = useRef(false), pending = useRef(false);
  const lastLoad = useRef(0), currentStatus = useRef('');
  const [loading, setLoading] = useState(false);
  const [newer, setNewer] = useState(false);
  const loadedToken = useRef('');

  const load = useCallback(async (id: string, force = true) => {
    if (!id || id !== currentSeed.current || (!force && pending.current)) return;
    const request = ++serial.current;
    pending.current = true;
    if (force) setLoading(true);
    try {
    const doc = await api.getAnalysis(id) as Row | null;
    if (id !== currentSeed.current || request !== serial.current) return;
    lastLoad.current = Date.now(); currentStatus.current = doc?.status || '';
    if (!force && dirty.current) {
      if (doc?.edit_token !== loadedToken.current) setNewer(true);
      return;
    }
    dirty.current = false; setNewer(false); setError(null);
    loadedToken.current = doc?.edit_token || '';
    setA(doc);
    if (doc) {
      const und = doc.understanding || {};
      setU({ ...und,
        observations: (und.observations || []).join("\n"),
        interpretations: (und.interpretations || []).join("\n"),
        uncertainties: (und.uncertainties || []).join("\n") });
      setSections(doc.timeline || []);
      setT(doc.treatment || {});
    }
    } finally {
      if (request === serial.current) {pending.current = false; setLoading(false);}
    }
  }, []);
  useEffect(() => {
    const report = (e: unknown) => {if (currentSeed.current === seedId) setError(e);};
    load(seedId).catch(report);
    const refresh = () => {
      if (document.visibilityState !== 'hidden') load(seedId, false).catch(report);
    };
    const timer = setInterval(() => {
      const period = ['in_progress','evidence_ready'].includes(currentStatus.current) ? 5000 : 30000;
      if (Date.now() - lastLoad.current >= period) refresh();
    }, 5000);
    document.addEventListener('visibilitychange', refresh);
    return () => {serial.current++; pending.current=false; clearInterval(timer); document.removeEventListener('visibilitychange', refresh);};
  }, [seedId, load]);

  const seed = seeds.find((x) => x.id === seedId);
  const bp = blueprints.find((x) => x.seed_id === seedId);
  const binding = bp?.analysis;
  const staleBinding = binding && a && binding.revision !== a.revision;
  const reviewerName = () => {
    if (!reviewer.trim()) throw new Error("Enter your reviewer name first.");
    return reviewer.trim();
  };
  const lines = (v: string) => v.split("\n").map((x) => x.trim()).filter(Boolean);
  const rerun = () => act(async () => {
    await api.rerunAnalysis(seedId, a?.edit_token); await load(seedId);
  }, "Evidence stages re-queued");
  const save = (section: string, body: Row) => act(async () => {
    await api.saveAnalysis(seedId, section, { ...body, edit_token: a?.edit_token, reviewer: reviewerName() });
    await load(seedId);
  }, `${section} saved`);

  const acq = a?.acquisition || {};
  const transcript = a?.transcript || {};
  const evidence = a?.evidence || {};
  const blocking: Row[] = a?.blocking || [];
  const transcriptBlocked = blocking.some((b) =>
    String(b.code).startsWith("transcript"));

  return <section aria-label="analysis" onChangeCapture={() => {dirty.current = true;}}>
    <h2>Deep reference analysis</h2>
    <p>Production requires a reviewed analysis bound to the exact source
      bytes. Preliminary observations and captions stay visible but can
      never qualify a blueprint on their own.</p>
    <select aria-label="Analysis source" value={seedId}
            onChange={(e) => {
              currentSeed.current = e.target.value; serial.current++; pending.current = false;
              dirty.current = false; setNewer(false); setA(null); setU({}); setSections([]); setT({});
              setNote(''); setTx({provider:'',provenance:'',words:''});
              setLoading(Boolean(e.target.value)); setSeed(e.target.value); setError(null);
            }}>
      <option value="">Select source</option>
      {seeds.map((x) => <option key={x.id} value={x.id}>
        {x.canonical_url || x.id}</option>)}
    </select>
    {error != null && <ErrorBox error={error} />}
    {loading && <p role="status">Loading this source…</p>}
    {newer && <p role="status">New analysis is available. Your edits have been kept.
      <button onClick={() => load(seedId).catch(setError)}>Discard edits and reload</button></p>}

    {seedId && !a && !loading && <>
      {seed?.source_asset_id
        ? <button onClick={() => act(async () => {
            await api.startAnalysis(seedId, reviewerName());
            await load(seedId);
          }, "Deep analysis queued — the worker is gathering evidence")}>
            Run deep analysis</button>
        : <Empty what="source media"
                 hint="Attach the verified download on the Seeds tab first." />}
    </>}

    {a && <fieldset disabled={loading} style={{border:0,padding:0}}>
      <h3>Status</h3>
      <p><strong>{a.status}</strong> · revision {a.revision}
        {a.stage ? ` · last stage ${a.stage}` : ""}</p>
      <ol aria-label="machine stages">
        {STAGES.map((s) => <li key={s}>
          {a.stages?.[s]?.done ? "✓" : "…"} {s}</li>)}
      </ol>
      <p>Capabilities: hypit {a.capabilities?.hypit ? "available" : "missing"}
        · whisperx {a.capabilities?.whisperx ? "configured" : "not configured"}</p>
      {bp && <p>Blueprint: {bp.status}
        {binding ? ` · bound to analysis r${binding.revision}` : ""}
        {staleBinding && <strong> — stale: analysis is now r{a.revision};
          re-accept the blueprint</strong>}</p>}

      {blocking.length > 0 && <Blocked
        why={blocking.map((b) => `${b.code}: ${b.detail}`).join(" · ")}
        action="resolve below, then re-run the evidence stages" />}
      {blocking.map((b, i) => <ul key={i}>
        {(b.recovery || []).map((r: string, j: number) =>
          <li key={j}>{r}</li>)}</ul>)}
      {(a.status === "blocked" || a.status === "in_progress") &&
        <button onClick={rerun}>Re-run evidence stages</button>}

      {acq.sha256 && <>
        <h3>Verified acquisition</h3>
        <p>{acq.width}×{acq.height} · {acq.duration_s}s · {acq.fps} fps ·
          audio {String(acq.audio_present)} · via {acq.via}</p>
        <p><code>{acq.sha256}</code></p>
      </>}

      <h3>Transcript</h3>
      <p>{transcript.status || "pending"}
        {transcript.provider ? ` · ${transcript.provider}` : ""}
        {transcript.preliminary ? " · preliminary only" : ""}
        {transcript.word_count ? ` · ${transcript.word_count} words` : ""}</p>
      {transcript.provenance && <p>{transcript.provenance}</p>}
      {transcriptBlocked && <>
        <h4>Import an aligned transcript</h4>
        <p>Paste word-timed output from your own alignment run (start/end
          in seconds on the source clock).</p>
        <label>Provider <input value={tx.provider}
          onChange={(e) => setTx({ ...tx, provider: e.target.value })}
          placeholder="e.g. whisperx large-v3" /></label>
        <label>Provenance <input value={tx.provenance}
          onChange={(e) => setTx({ ...tx, provenance: e.target.value })}
          placeholder="how and where it was produced" /></label>
        <textarea aria-label="Transcript words JSON" rows={6} value={tx.words}
          onChange={(e) => setTx({ ...tx, words: e.target.value })}
          placeholder='{"words":[{"word":"...","start_s":0,"end_s":0.4}]}' />
        <button onClick={() => act(async () => {
          const doc = JSON.parse(tx.words);
          await api.importTranscript(seedId, {
            provider: tx.provider, provenance: tx.provenance,
            confidence: doc.confidence || "word-level",
            language: doc.language, words: doc.words,
            edit_token: a.edit_token,
            reviewer: reviewerName() });
          await load(seedId);
        }, "Transcript imported")}>Import transcript</button>
        <h4>Or declare the source non-verbal</h4>
        <label>Supporting evidence <input value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="what shows there is no speech (e.g. music-only)" /></label>
        <button onClick={() => act(async () => {
          await api.declareAnalysis(seedId, {
            status: "declared_nonverbal", note,
            edit_token: a.edit_token,
            reviewer: reviewerName() });
          await load(seedId);
        }, "Declared non-verbal")}>Declare non-verbal</button>
      </>}

      {!!(evidence.grids || []).length && <>
        <h3>Timed evidence</h3>
        <p>{evidence.grids.length} grids · coverage {evidence.coverage_s}s
          {(evidence.boundaries || []).length > 0 &&
            ` · cuts at ${(evidence.boundaries || [])
              .map((c: Row) => `${c.t}s`).join(", ")}`}</p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {evidence.grids.map((g: Row, i: number) =>
            <figure key={i} style={{ margin: 0 }}>
              <img src={media(g.artifact_id)} style={{ maxHeight: 180 }}
                   alt={`grid ${g.start_s}–${g.end_s}s`} />
              <figcaption>{g.start_s}–{g.end_s}s
                {g.transcript_linked ? " · transcript-linked" : ""}</figcaption>
            </figure>)}
        </div>
      </>}

      <h3>Whole-piece understanding</h3>
      {UNDERSTANDING.map(([k, label]) =>
        <label key={k} style={{ display: "block" }}>{label}
          <textarea rows={2} value={u[k] || ""}
            onChange={(e) => setU({ ...u, [k]: e.target.value })} /></label>)}
      <label style={{ display: "block" }}>Observed facts — one per line
        <textarea rows={3} value={u.observations || ""}
          onChange={(e) => setU({ ...u, observations: e.target.value })} /></label>
      <label style={{ display: "block" }}>Interpretation — one per line
        <textarea rows={3} value={u.interpretations || ""}
          onChange={(e) => setU({ ...u, interpretations: e.target.value })} /></label>
      <label style={{ display: "block" }}>Uncertainties — one per line
        <textarea rows={2} value={u.uncertainties || ""}
          onChange={(e) => setU({ ...u, uncertainties: e.target.value })} /></label>
      <button onClick={() => save("understanding", { ...u,
        observations: lines(u.observations || ""),
        interpretations: lines(u.interpretations || ""),
        uncertainties: lines(u.uncertainties || "") })}>
        Save understanding</button>

      <h3>Timeline</h3>
      {sections.map((s, i) => <div key={i}>
        <input aria-label="start" type="number" step="0.1" value={s.start_s}
          onChange={(e) => setSections(sections.map((x, j) => j === i
            ? { ...x, start_s: Number(e.target.value) } : x))} />
        <input aria-label="end" type="number" step="0.1" value={s.end_s}
          onChange={(e) => setSections(sections.map((x, j) => j === i
            ? { ...x, end_s: Number(e.target.value) } : x))} />
        <input aria-label="phase" value={s.phase} placeholder="phase"
          onChange={(e) => setSections(sections.map((x, j) => j === i
            ? { ...x, phase: e.target.value } : x))} />
        <input aria-label="summary" value={s.summary} placeholder="what happens"
          onChange={(e) => setSections(sections.map((x, j) => j === i
            ? { ...x, summary: e.target.value } : x))} />
        <button onClick={() => {dirty.current=true; setSections(sections.filter((_, j) => j !== i));}}>
          Remove</button>
      </div>)}
      <button onClick={() => {dirty.current=true; setSections([...sections,
        { start_s: 0, end_s: 0, phase: "", summary: "" }]);}}>
        Add section</button>
      <button onClick={() => save("timeline", { sections })}>
        Save timeline</button>

      <h3>Treatment</h3>
      {TREATMENT.map(([k, label]) =>
        <label key={k} style={{ display: "block" }}>{label}
          <textarea rows={3} value={t[k] || ""}
            onChange={(e) => setT({ ...t, [k]: e.target.value })} /></label>)}
      <label style={{ display: "block" }}>Prompt notes for generation
        <textarea rows={2} value={t.prompt_notes || ""}
          onChange={(e) => setT({ ...t, prompt_notes: e.target.value })} /></label>
      <button onClick={() => save("treatment", t)}>Save treatment</button>

      <h3>Review</h3>
      {a.review?.verdict
        ? <p>Reviewed by {a.review.reviewer} at {a.review.at}
            {a.review.notes ? ` — ${a.review.notes}` : ""}</p>
        : <p>Not yet reviewed.</p>}
      {a.status === "awaiting_review" &&
        <button onClick={() => act(async () => {
          await api.reviewAnalysis(seedId, {
            edit_token: a.edit_token,
            reviewer: reviewerName(), verdict: "accept" });
          await load(seedId);
        }, "Analysis complete — blueprint can now be accepted")}>
          Mark analysis complete</button>}
    </fieldset>}
  </section>;
}
