import React,{useState} from 'react';
import {call} from '../../api/client';
type Row=Record<string,any>;
type Props={section:string;data:Record<string,Row[]>;selected:Row|null;reviewer:string;act:(fn:()=>Promise<unknown>,message?:string)=>Promise<unknown>};
const expires=()=>new Date(Date.now()+3600000).toISOString();
export function OperationsScreen({section,data,selected,reviewer,act}:Props){
  const [unit,setUnit]=useState('jimeng_credits'),[ceiling,setCeiling]=useState('0'),[budgetId,setBudget]=useState('');
  const [query,setQuery]=useState(''),[platform,setPlatform]=useState('youtube'),[handle,setHandle]=useState('');
  const [effect,setEffect]=useState<Row|null>(null),[authority,setAuthority]=useState('');
  const [voice,setVoice]=useState(''),[segment,setSegment]=useState(''),[variant,setVariant]=useState('A');
  const [speechJob,setSpeechJob]=useState(''),[speech,setSpeech]=useState<Row|null>(null),[fitJob,setFitJob]=useState('');
  const [account,setAccount]=useState(''),[title,setTitle]=useState(''),[publication,setPublication]=useState<Row|null>(null);
  const [horizon,setHorizon]=useState('48h'),[exposure,setExposure]=useState('1000');
  const eid=selected?.experiment?.experiment_id||selected?.id,rev=selected?.revision;
  function reviewed(){if(!reviewer.trim())throw new Error('Enter your reviewer name first.');return reviewer.trim();}
  const post=(path:string,body:Row={},revision?:number)=>call<Row>('POST',path,{body,rev:revision});
  const plans=(data.effect_plans||[]).filter(p=>section==='Research'?p.provider==='viral_outliers':section==='Products'?p.provider==='shopify':section==='Analysis'?p.kind==='analysis':p.kind==='tts'&&p.experiment_id===eid);
  const route=effect?.provider==='viral_outliers'?'research':'effects';
  const selectedSegment=(selected?.variants||[]).find((v:Row)=>v.variant_key===variant)?.segments?.find((s:Row)=>s.id===segment);
  return <section><h2>{section}</h2>
    {section==='Budgets'&&<><p>Each provider keeps its own unit. Recording a ceiling does not buy credits.</p>
      <label>Budget name<input value={budgetId} onChange={e=>setBudget(e.target.value)}/></label>
      <label>Unit<select value={unit} onChange={e=>setUnit(e.target.value)}>{['jimeng_credits','usd_micros','elevenlabs_credits','viral_outliers_credits'].map(x=><option key={x}>{x}</option>)}</select></label>
      <label>Ceiling in this unit<input type="number" min="0" step="1" value={ceiling} onChange={e=>setCeiling(e.target.value)}/></label>
      <button onClick={()=>act(()=>post('/api/budgets',{id:budgetId,unit,scope:'aggregate',scope_key:'',ceiling:Number(ceiling),reviewer:reviewed(),evidence:'Explicit dashboard budget scope'}),'Budget recorded')}>Record spending ceiling</button>
      <table><thead><tr><th>Budget</th><th>Unit</th><th>Ceiling</th><th>Available</th></tr></thead><tbody>{(data.budgets||[]).map(b=><tr key={b.id}><td>{b.id}</td><td>{b.unit}</td><td>{b.cap_amount}</td><td>{b.retired?'Retired after restore':b.available}</td></tr>)}</tbody></table></>}
    {section==='Research'&&<><p>Prepare quotes, approve their funding, then start research. Creator history is evaluated separately from search results.</p>
      <label>Search topic<input value={query} onChange={e=>setQuery(e.target.value)}/></label><label>Platform<select value={platform} onChange={e=>setPlatform(e.target.value)}>{['youtube','tiktok','instagram'].map(x=><option key={x}>{x}</option>)}</select></label>
      <label>Creator handle for baseline (optional)<input value={handle} onChange={e=>setHandle(e.target.value)}/></label>
      <button onClick={()=>act(async()=>{const r=await post('/api/research/plans',{requests:[{kind:handle?'creator_history':'search',query,handle,platforms:[platform],page:1,page_size:100}]});setEffect(r.plan);setAuthority('');},'Research quote prepared')}>Prepare research quote</button>
      <button onClick={()=>act(()=>post('/api/research/evaluate',{plan_ids:plans.map(p=>p.id),policy:{mode:'either',baseline_threshold:5,follower_threshold:2}}),'Evaluation queued')}>Evaluate completed searches and histories</button>
      <pre>{JSON.stringify(data.research||[],null,2)}</pre></>}
    {section==='Analysis'&&<><p>Analyze registered source video with a qualified model. Review the resulting timing in Seeds.</p>
      <label>Source seed<select value={account} onChange={e=>setAccount(e.target.value)}><option value="">Choose source</option>{(data.seeds||[]).map(x=><option key={x.id}>{x.id}</option>)}</select></label>
      <label>Qualified analysis model<input value={voice} onChange={e=>setVoice(e.target.value)}/></label>
      <button onClick={()=>act(async()=>{const r=await post(`/api/seeds/${account}/analysis/prepare`,{model:voice});setEffect(r.plan);setAuthority('');},'Analysis quote prepared')}>Prepare analysis quote</button>
      <label>Completed analysis job<input value={speechJob} onChange={e=>setSpeechJob(e.target.value)}/></label>
      <button onClick={()=>act(()=>post(`/api/seeds/${account}/analysis/collect`,{job_id:speechJob,reviewer:reviewed()}),'Blueprint collection queued')}>Collect completed analysis</button>
    </>}
    {section==='Audio'&&<><p>Use ElevenLabs v3 for the selected copy. Review fitted speech before attaching it to a new revision. Import licensed music in Seeds.</p>
      <label>Variant<select value={variant} onChange={e=>setVariant(e.target.value)}>{'ABCD'.split('').map(x=><option key={x}>{x}</option>)}</select></label>
      <label>Segment<select value={segment} onChange={e=>setSegment(e.target.value)}><option value="">Choose a segment</option>{(selected?.variants||[]).find((v:Row)=>v.variant_key===variant)?.segments?.map((s:Row)=><option key={s.id}>{s.id}</option>)}</select></label>
      <p>Copy: {selectedSegment?.copy||'Add copy in the plan first.'}</p><label>ElevenLabs voice ID<input value={voice} onChange={e=>setVoice(e.target.value)}/></label>
      <button onClick={()=>act(async()=>{if(!selectedSegment?.copy)throw new Error('Select a segment with spoken copy.');const r=await post('/api/effects/plans',{kind:'tts',provider:'elevenlabs',model:'eleven_v3',experiment_id:eid,requests:[{text:selectedSegment.copy,voice_id:voice,model:'eleven_v3',language:'en',settings:{}}]},rev);setEffect(r.plan);setAuthority('');},'Speech quote prepared')}>Prepare speech quote</button>
      <label>Completed synthesis job<input value={speechJob} onChange={e=>setSpeechJob(e.target.value)}/></label>
      <button onClick={()=>act(async()=>{const r=await post(`/api/experiments/${eid}/speech/fit`,{variant_key:variant,segment_id:segment,job_id:speechJob},rev);setFitJob(r.job_id);},'Speech fitting queued')}>Fit speech to segment</button>
      {fitJob&&<button onClick={()=>act(async()=>{const j=await call<Row>('GET',`/api/jobs/${fitJob}`);if(j.status!=='succeeded')throw new Error(`Speech fitting: ${j.status}`);setSpeech(j.command.result.speech);})}>Load fitted speech</button>}
      {speech&&<><audio controls src={`/api/assets/${speech.artifact_id}/media`}/><p>{speech.text} · {speech.duration_s}s</p>
        <button onClick={()=>act(async()=>setSpeech(await post(`/api/speech/${speech.id}/approve`,{speech_hash:speech.speech_hash,reviewer:reviewed()})),'Speech accepted')}>Accept this speech</button>
        <button disabled={speech.status!=='approved'} onClick={()=>act(()=>post(`/api/experiments/${eid}/speech/attach`,{speech_ids:[speech.id]},rev),'New revision created; quote and review it again')}>Attach approved speech and captions</button></>}
    </>}
    {(['Research','Audio','Products','Analysis'].includes(section))&&<><h3>Reviewed effect plans</h3><select aria-label="Effect plan" value={effect?.id||''} onChange={e=>{setEffect(plans.find(p=>p.id===e.target.value)||null);setAuthority('');}}><option value="">Choose a quote</option>{plans.map(p=><option key={p.id} value={p.id}>{p.id}</option>)}</select>
      {effect&&<><pre>{JSON.stringify({plan:effect.id,hash:effect.plan_hash,account:effect.account,model:effect.model,quotes:effect.operations.map((x:Row)=>x.price),ceilings:effect.total},null,2)}</pre>
      <label>Funded budget<select value={budgetId} onChange={e=>setBudget(e.target.value)}><option value="">Choose funding</option>{(data.budgets||[]).filter(b=>!b.id.startsWith('authority:')&&!b.retired).map(b=><option key={b.id}>{b.id}</option>)}</select></label>
      <button onClick={()=>act(async()=>{const r=await post(`/api/${route}/plans/${effect.id}/authorize`,{plan_hash:effect.plan_hash,ceilings:effect.total,budget_ids:[budgetId],reviewer:reviewed(),valid_until:expires()});setAuthority(r.authorization_id);},'Exact quote approved')}>Approve displayed quote</button>
      <button disabled={!authority} onClick={()=>act(async()=>{const r=await post(`/api/${route}/plans/${effect.id}/run`,{authorization_id:authority});setSpeechJob(r.jobs?.[0]?.job_id||'');},'Approved work queued')}>Start approved work</button></>}</>}
    {section==='Publishing'&&<><p>Freeze the evaluation policy in Learning before planning posts. Publication requires reviewed finals and verified delivery.</p>
      <label>Platform<select value={platform} onChange={e=>setPlatform(e.target.value)}>{['youtube','tiktok','instagram'].map(x=><option key={x}>{x}</option>)}</select></label><label>Configured account<input value={account} onChange={e=>setAccount(e.target.value)}/></label><label>Post title<input value={title} onChange={e=>setTitle(e.target.value)}/></label>
      {(selected?.variants||[]).filter((v:Row)=>v.final).map((v:Row)=><button key={v.id} onClick={()=>act(async()=>{const checks=[...v.final.check_ids,...(data.reviews||[]).filter(r=>r.check_type==='creative'&&r.verdict==='pass'&&r.target_hash===v.final.sha256).map(r=>r.id)];const r=await post(`/api/variants/${v.id}/publications`,{reviewer:reviewed(),platform,account_id:account,metadata:{title},check_ids:checks},rev);setPublication(r.publication);},'Publication plan created')}>Plan post {v.variant_key}</button>)}
      <select aria-label="Publication" value={publication?.id||''} onChange={e=>setPublication((data.publications||[]).find(p=>p.id===e.target.value)||null)}><option value="">Choose publication</option>{(data.publications||[]).map(p=><option key={p.id}>{p.id}</option>)}</select>
      {publication&&<><pre>{JSON.stringify(publication,null,2)}</pre><button onClick={()=>act(()=>post(`/api/publications/${publication.id}/authorize`,{final_sha256:publication.final_sha256,platform:publication.platform,account_id:publication.account_id,action:'publish',reviewer:reviewed(),valid_until:expires()}),'Exact publication approved')}>Authorize this final and account</button><button onClick={()=>act(()=>post(`/api/publications/${publication.id}/run`),'Publication queued')}>Publish approved post</button><button onClick={()=>act(()=>post(`/api/publications/${publication.id}/observe`),'Status check queued')}>Refresh remote status</button></>}
    </>}
    {section==='Learning'&&<><label>Evaluation horizon<select value={horizon} onChange={e=>setHorizon(e.target.value)}>{['48h','7d','28d'].map(x=><option key={x}>{x}</option>)}</select></label><label>Minimum thumbnail impressions per variant<input type="number" min="1" value={exposure} onChange={e=>setExposure(e.target.value)}/></label>
      <button onClick={()=>act(()=>post(`/api/experiments/${eid}/policy`,{reviewer:reviewed(),policy_version:'operator.v1',primary_metric:'thumbnail_ctr',horizon,min_exposure:Number(exposure),exposure_metric:'thumbnail_impressions',practical_lift:0.1,promote_min_independent_experiments:2},rev),'Policy frozen')}>Freeze policy before publication</button>
      {(data.publications||[]).filter(p=>p.variant_plan_id?.startsWith(eid+':')).map(p=><button key={p.id} onClick={()=>act(()=>post(`/api/publications/${p.id}/readbacks`,{horizon}),'Readback queued')}>Collect {horizon}: {p.variant_plan_id}</button>)}
      <button onClick={()=>act(()=>post(`/api/experiments/${eid}/decisions`,{},rev),'Decision queued')}>Evaluate current evidence</button><pre>{JSON.stringify({policies:data.policies,metrics:data.metrics,decisions:data.decisions},null,2)}</pre>
    </>}
    {section==='Products'&&<><label>Configured shop (myshopify.com)<input value={account} onChange={e=>setAccount(e.target.value)}/></label><label>Product handles, comma separated<input value={query} onChange={e=>setQuery(e.target.value)}/></label><button onClick={()=>act(async()=>{const r=await post('/api/products/import-plan',{shop:account,selection:query.split(',').map(x=>x.trim()).filter(Boolean),reviewer:reviewed()});setEffect(r.plan);setAuthority('');},'Read-only import prepared')}>Prepare product import</button><p>Product snapshots and available reference assets.</p><pre>{JSON.stringify(data.products||[],null,2)}</pre></>}
  </section>;
}
