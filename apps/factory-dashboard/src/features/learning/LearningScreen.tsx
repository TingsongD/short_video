import React,{useState} from 'react';
import {call} from '../../api/client';
type Row=Record<string,any>;
type Props={data:Record<string,Row[]>;selected:Row|null;reviewer:string;act:(fn:()=>Promise<unknown>,message?:string)=>Promise<unknown>};
const HORIZONS=['24h','48h','72h','7d','28d','7d_complete','28d_complete'] as const;
const PLATFORMS=['youtube','tiktok','instagram','facebook'] as const;

/** PL-05/PL-06: per-platform decisions, best-of-four seed selection
 * (A is a legal winner), provisional vs mature evidence labels, loop
 * policy and Round-2 proposals with pause/cancel semantics. */
export function LearningScreen({data,selected,reviewer,act}:Props){
  const [horizon,setHorizon]=useState('48h'),[exposure,setExposure]=useState('1000');
  const [weights,setWeights]=useState<Record<string,string>>({youtube:'1',tiktok:'0',instagram:'0',facebook:'0'});
  const [rule,setRule]=useState('weighted_lift'),[minPlat,setMinPlat]=useState('2');
  const [selHorizon,setSelHorizon]=useState('48h'),[selection,setSelection]=useState<Row|null>(null);
  const [maxRounds,setMaxRounds]=useState('1'),[mode,setMode]=useState('propose_only');
  const [customSeries,setCustomSeries]=useState(''),[authzId,setAuthzId]=useState('');
  const eid=selected?.experiment?.experiment_id||selected?.id,rev=selected?.revision;
  function reviewed(){if(!reviewer.trim())throw new Error('Enter your reviewer name first.');return reviewer.trim();}
  const post=(path:string,body:Row={},revision?:number)=>call<Row>('POST',path,{body,rev:revision});
  const pubs=(data.publications||[]) as Row[];
  const decisions=(data.decisions||[]) as Row[];
  const selections=(data.selections||[]) as Row[];
  const loops=(data.loops||[]) as Row[];
  const lineages=(data.lineages||[]) as Row[];
  const enabled=PLATFORMS.filter(p=>Number(weights[p])>0);
  const total=enabled.reduce((a,p)=>a+Number(weights[p]||0),0);
  const seedPolicy=enabled.length?{mode:'weighted_rank',
    weights:Object.fromEntries(enabled.map(p=>[p,Number(weights[p])/total])),
    provisional_horizon:'48h',
    improvement_rule:rule==='min_platforms'?{kind:'min_platforms',min_platforms:Number(minPlat)}:{kind:'weighted_lift'}}:undefined;
  // A fresh series has no loops/lineages yet — derive the candidate id
  // from the selected experiment's seed group so the first loop can be
  // frozen here; a manual id stays available as a fallback.
  const selectedSeed=(data.seeds||[]).find(x=>x.id===(selected?.experiment?.seed_id||selected?.seed_id));
  const suggested=selectedSeed?`series:${selectedSeed.independence_group||selectedSeed.lineage_root_id||selectedSeed.id}`:'';
  const extra=[suggested,customSeries.trim()].filter(Boolean);
  const seriesIds=[...new Set(lineages.map(l=>l.series_id).concat(loops.map(l=>l.series_id),extra))];
  return <section><h2>Learning</h2>
    <p>Decisions are control-relative per destination; seed selection ranks all four — A can win. Evidence is observational, never causal.</p>
    <h3>Freeze evaluation policy</h3>
    <label>Evaluation horizon<select value={horizon} onChange={e=>setHorizon(e.target.value)}>{HORIZONS.map(x=><option key={x}>{x}</option>)}</select></label>
    <label>Minimum exposure per variant<input type="number" min="1" value={exposure} onChange={e=>setExposure(e.target.value)}/></label>
    <p>Seed-selection weights (normalized at freeze): {PLATFORMS.map(p=><label key={p} style={{marginRight:8}}>{p} <input style={{width:56}} value={weights[p]} onChange={e=>setWeights({...weights,[p]:e.target.value})}/></label>)}</p>
    <label>Improvement rule<select value={rule} onChange={e=>setRule(e.target.value)}><option value="weighted_lift">weighted_lift</option><option value="min_platforms">min_platforms</option></select></label>
    {rule==='min_platforms'&&<label>Platforms beaten<input type="number" min="1" max={enabled.length||1} value={minPlat} onChange={e=>setMinPlat(e.target.value)}/></label>}
    <button onClick={()=>act(()=>post(`/api/experiments/${eid}/policy`,{reviewer:reviewed(),policy_version:'operator.v1',primary_metric:'views',horizon,min_exposure:Number(exposure),exposure_metric:'views',practical_lift:0.1,promote_min_independent_experiments:2,seed_policy:seedPolicy},rev),'Policy frozen')}>Freeze policy before publication</button>
    <h3>Observations</h3>
    <p>Checkpoints are scheduled automatically once a post is confirmed public. Trigger a manual readback below.</p>
    {pubs.map(p=><button key={p.id} onClick={()=>act(()=>post(`/api/publications/${p.id}/readbacks`,{horizon:selHorizon}),'Readback queued')}>Collect {selHorizon}: {p.variant_plan_id}·{p.platform}</button>)}
    <h3>Decisions (per platform)</h3>
    <table><thead><tr><th>Decision</th><th>Platform</th><th>Horizon</th><th>Conclusion</th><th>Winner</th></tr></thead><tbody>
      {decisions.map(d=><tr key={d.id}><td>{d.id}</td><td>{d.platform||'—'}</td><td>{d.horizon}</td><td>{d.conclusion}</td><td>{d.winner||'—'}</td></tr>)}
    </tbody></table>
    <button onClick={()=>act(()=>post(`/api/experiments/${eid}/decisions`,{horizon,platform:''},rev),'Decision queued')}>Evaluate current evidence</button>
    {PLATFORMS.map(p=><button key={p} onClick={()=>act(()=>post(`/api/experiments/${eid}/decisions`,{horizon,platform:p},rev),'Decision queued')}>Decide {p}</button>)}
    <h3>Seed selection</h3>
    <label>Checkpoint<select value={selHorizon} onChange={e=>setSelHorizon(e.target.value)}>{HORIZONS.map(x=><option key={x}>{x}</option>)}</select></label>
    <button onClick={()=>act(()=>post(`/api/experiments/${eid}/selections`,{horizon:selHorizon},rev),'Selection evaluation queued')}>Evaluate seed at {selHorizon}</button>
    <table><thead><tr><th>Selection</th><th>Horizon</th><th>Status</th><th>Winner</th><th>Seed</th></tr></thead><tbody>
      {selections.map(s=><tr key={s.id}><td><button onClick={()=>setSelection(s)}>{s.id}</button></td><td>{s.horizon}</td><td>{s.status}{s.horizon?.includes('complete')?' (mature)':' (provisional)'}</td><td>{s.winner_variant||'—'}</td><td>{s.seed_id||'—'}</td></tr>)}
    </tbody></table>
    {selection&&<details open><summary>{selection.id}</summary><pre>{JSON.stringify(selection.basis,null,2)}</pre>
      {['provisional','confirmed'].includes(selection.status)&&selection.winner_variant&&<button onClick={()=>act(()=>post(`/api/experiments/${eid}/rounds`,{selection_id:selection.id},rev),'Round proposal created')}>Propose next round from this selection</button>}
    </details>}
    <h3>Loop policy and lineage</h3>
    <label>Mode<select value={mode} onChange={e=>setMode(e.target.value)}><option value="propose_only">propose_only</option><option value="execute_within_authorization">execute_within_authorization</option></select></label>
    <label>Max rounds<input type="number" min="1" value={maxRounds} onChange={e=>setMaxRounds(e.target.value)}/></label>
    {mode==='execute_within_authorization'&&<label>Authorization id<input value={authzId} onChange={e=>setAuthzId(e.target.value)} placeholder="auth-… required to execute"/></label>}
    <p>A series id is derived from the seed's lineage group — e.g. series:&lt;independence_group&gt;. Freeze binds continuation authority before any child is proposed.</p>
    <label>Series id<input value={customSeries} onChange={e=>setCustomSeries(e.target.value)} placeholder={suggested||'series:<group>'}/></label>
    {seriesIds.map(sid=>{const loop=loops.find(l=>l.series_id===sid);const children=lineages.filter(l=>l.series_id===sid);return <details key={sid}><summary>{sid} — {loop?.status||'no policy'}</summary>
      {!loop&&<button onClick={()=>act(()=>post(`/api/series/${encodeURIComponent(sid)}/loop`,{reviewer:reviewed(),mode,max_rounds:Number(maxRounds),authorization_id:authzId||undefined}),'Loop policy frozen')}>Freeze loop for {sid}</button>}
      <table><thead><tr><th>Round</th><th>Seed</th><th>Basis</th><th>Status</th></tr></thead><tbody>
        {children.map(c=><tr key={c.id}><td>{c.round}</td><td>{c.seed_id}</td><td>{c.parent_selection_id}</td><td>{c.status}</td></tr>)}
      </tbody></table>
      {loop?.status==='active'&&<><button onClick={()=>act(()=>post(`/api/series/${encodeURIComponent(sid)}/pause`),'Series paused — remote schedules still fire')}>Pause local work</button>
        <button onClick={()=>act(()=>post(`/api/series/${encodeURIComponent(sid)}/cancel`),'Series cancelled — remote schedules enumerated')}>Cancel series + remote schedules</button></>}
    </details>;})}
    <h3>Raw evidence</h3>
    <pre>{JSON.stringify({policies:data.policies,metrics:(data.metrics||[]).length},null,2)}</pre>
  </section>;
}
