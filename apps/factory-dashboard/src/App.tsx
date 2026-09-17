import React, { useCallback, useEffect, useState } from "react";
import { api, call, events, ProviderReadiness, session } from "./api/client";
import { ProvidersScreen } from "./features/providers/ProvidersScreen";
import { CompareScreen } from "./features/compare/CompareScreen";
import { ReviewsScreen } from "./features/reviews/ReviewsScreen";
import { DeliveryScreen } from "./features/delivery/DeliveryScreen";
import { GenerationApproval } from "./features/operations/GenerationApproval";
import { OperationsScreen } from "./features/operations/OperationsScreen";
import { QueueScreen, JobView } from "./features/queue/QueueScreen";

// The server owns these JSON domain records. The editor round-trips unknown
// optional fields; IDs, revision and hashes always come from the selected row.
type Row = Record<string, any>;
const TABS = ["Seeds", "Plan", "Queue", "Compare", "Reviews", "Delivery", "Studio", "Providers", "Products", "Budgets", "Research", "Analysis", "Audio", "Publishing", "Learning"] as const;
const names = ["seeds","blueprints","templates","experiments","plans","assets","reviews","deliveries","products","budgets","research","effect_plans","publications","metrics","policies","decisions"];

export default function App() {
  const [tab,setTab]=useState<(typeof TABS)[number]>("Seeds");
  const [data,setData]=useState<Record<string,Row[]>>({});
  const [jobs,setJobs]=useState<Row[]>([]);
  const [providers,setProviders]=useState<Record<string,ProviderReadiness>>({});
  const [health,setHealth]=useState<Row>({});
  const [error,setError]=useState(""); const [notice,setNotice]=useState("");
  const [seedId,setSeed]=useState(""); const [experimentId,setExperiment]=useState(window.localStorage.getItem("selected-experiment")||"");
  const [selected,setSelected]=useState<Row|null>(null);
  const [url,setUrl]=useState(""); const [reviewer,setReviewer]=useState("");
  const [observations,setObservations]=useState('{"beats":[],"transcript":[],"music":{"role":"unknown"}}');
  const [draft,setDraft]=useState(""); const [folder,setFolder]=useState(""); const [account,setAccount]=useState("");
  const [busy,setBusy]=useState(false); const [comment,setComment]=useState(""); const [at,setAt]=useState("0");
  const [studioVariant,setStudioVariant]=useState(""); const [studioSessions,setStudioSessions]=useState<Row[]>([]);
  const studioSession=studioSessions.find(x=>x.owner===studioVariant && x.state==='open');
  const refresh=useCallback(async()=>{
    const [collections,q,h,p,studios]=await Promise.all([
      Promise.all(names.map(async n=>[n,(await call<{items:Row[]}>("GET",`/api/collections/${n}`)).items] as const)),
      call<{items:{jobs:Row[]}}>("GET","/api/collections/queue"),api.health(),api.providers(),call<{items:Row[]}>("GET","/api/studio/sessions")]);
    setStudioSessions(studios.items);setData(Object.fromEntries(collections));setJobs(q.items.jobs);setHealth(h);setProviders(p);
    if(experimentId) setSelected(await api.results(experimentId));
  },[experimentId]);
  useEffect(()=>{window.localStorage.setItem("selected-experiment",experimentId);setSelected(null);
    let stream:EventSource|undefined; let disposed=false;
    session().then(refresh).then(()=>{if(!disposed)stream=events("factory",()=>{refresh().catch(e=>setError(String(e)));});}).catch(e=>setError(String(e)));
    const timer=setInterval(()=>refresh().catch(e=>setError(String(e))),5000);
    return ()=>{disposed=true;stream?.close();clearInterval(timer);};
  },[refresh,experimentId]);
  async function act(fn:()=>Promise<unknown>,message="Saved") {setBusy(true);setError("");try{const r=await fn();setNotice(message);await refresh();return r;}catch(e){setError(e instanceof Error?e.message:String(e));}finally{setBusy(false);}}
  function requireReviewer(){if(!reviewer.trim())throw new Error("Enter your reviewer name first.");return reviewer.trim();}
  const seeds=data.seeds||[];const seed=seeds.find(x=>x.id===seedId);
  const blueprint=(data.blueprints||[]).find(x=>x.seed_id===seedId);
  const plan=(data.plans||[]).find(x=>x.experiment_id===experimentId&&x.experiment_revision===selected?.revision);
  const variants=(selected?.variants||[]) as Row[];
  const reviews=data.reviews||[];const finals=variants.filter(v=>v.final);
  const media=(id:string)=>`/api/assets/${encodeURIComponent(id)}/media`;
  const videoAssets=(data.assets||[]).filter(x=>x.kind==='video');
  const selectedSeed=(data.seeds||[]).find(x=>x.id===selected?.experiment?.seed_id);
  const clock=selected?.experiment?.output_clock;const fps=clock?clock.num/clock.den:30;
  const compare=[...(selectedSeed?.source_asset_id?[{key:'source',label:'Reference',media_url:media(selectedSeed.source_asset_id),media_sha:''}]:[]),
    ...finals.map(v=>({key:v.variant_key,label:`${v.variant_key} · revision ${v.experiment_revision}`,media_url:media(v.final.artifact_id),media_sha:v.final.sha256,
      duration_s:v.target_frames/fps,regions:v.allowed_regions.map((r:Row)=>({start_s:r.start/fps,end_s:r.end/fps,label:v.changed_factor}))}))];
  async function makeDraft(){
    if(!blueprint||blueprint.status!=='accepted'||!seed?.source_asset_id)throw new Error('Accept a source blueprint first.');
    let template=(data.templates||[]).find(t=>t.derived_from_blueprint===blueprint.content_hash);
    if(!template)template=(await call<{template:Row}>('POST','/api/templates',{body:{blueprint_id:blueprint.id}})).template;
    const segments=blueprint.beats.map((b:Row)=>({id:b.id,slot_id:b.id,role:b.role,target:b.target,copy:'',speech:{},
      picture:{artifact_id:seed.source_asset_id,source_in_s:b.target.start_frame/(blueprint.clock.num/blueprint.clock.den)},captions:[],transition:'cut',claims:[]}));
    const variations=['B','C','D'].map((key,i)=>{const pos=[0,Math.floor(segments.length/2),segments.length-1][i];const changed=structuredClone(segments);
      changed[pos].captions=[{text:`Write your ${['hook','body','ending'][i]} caption`,...changed[pos].target}];
      return{key,factor:['hook','body','ending'][i],regions:[segments[pos].target],segments:changed,hypothesis:'Write the specific hypothesis',primary_metric:'retention',allowed_fields:['captions']};});
    setDraft(JSON.stringify({id:crypto.randomUUID(),blueprint_id:blueprint.id,template_id:template.id,segments,variants:variations,music:{artifact_id:'SELECT_IMPORTED_AUDIO',gain:1,provenance:'Describe permission or license'}},null,2));
    setTab('Plan');
  }
  return <main>
    <h1>Viral Video Factory</h1><p>Mode: {String(health.mode||'offline')} · Worker: {health.worker?.available?'running':'not connected'}</p>
    <label>Reviewer <input value={reviewer} onChange={e=>setReviewer(e.target.value)} placeholder="Your name"/></label>
    <label>Experiment <select value={experimentId} onChange={e=>setExperiment(e.target.value)}><option value="">Select an experiment</option>{(data.experiments||[]).map(x=><option key={x.id} value={x.experiment_id}>{x.experiment_id} · revision {x.revision}</option>)}</select></label>
    <nav>{TABS.map(x=><button key={x} aria-current={tab===x?'page':undefined} onClick={()=>setTab(x)}>{x}</button>)}</nav>
    {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
    <fieldset disabled={busy} style={{border:0,padding:0}}>
    {tab==='Seeds'&&<section><h2>Reference and imported media</h2>
      <label>Source video link <input value={url} onChange={e=>setUrl(e.target.value)}/></label><button onClick={()=>act(async()=>{const r=await api.createSeed(url) as Row;setSeed(r.seed.seed.id);})}>Add source</button>
      <select aria-label="Source" value={seedId} onChange={e=>setSeed(e.target.value)}><option value="">Select source</option>{seeds.map(x=><option key={x.id} value={x.id}>{x.canonical_url||x.id}</option>)}</select>
      <label>Import footage, narration or music <input type="file" accept="video/*,audio/*,image/*" onChange={e=>{const f=e.target.files?.[0];if(f)act(()=>api.importFile(f),'Media imported');}}/></label>
      {seed&&<><select aria-label="Attach source media" defaultValue="" onChange={e=>{if(e.target.value)act(()=>call('POST',`/api/seeds/${seedId}/media`,{body:{artifact_id:e.target.value}}));}}><option value="">Attach imported source video</option>{videoAssets.map(x=><option key={x.id} value={x.id}>{x.id}</option>)}</select>
      {seed.source_asset_id&&<video controls src={media(seed.source_asset_id)} style={{maxHeight:320}}/>}
      <h3>Observed timing and transcript</h3><p>Import your observations, then review the extracted source evidence.</p>
      <textarea aria-label="Source observations" rows={10} value={observations} onChange={e=>setObservations(e.target.value)}/><button onClick={()=>act(()=>call('POST',`/api/seeds/${seedId}/analyze`,{body:{reviewer:requireReviewer(),observations:JSON.parse(observations)}}),'Analysis queued')}>Analyze imported observations</button>
      {blueprint&&<><pre>{JSON.stringify(blueprint.beats,null,2)}</pre><button disabled={blueprint.status==='accepted'} onClick={()=>act(()=>call('POST',`/api/blueprints/${blueprint.id}/review`,{body:{content_hash:blueprint.content_hash,reviewer:requireReviewer()}}))}>Accept source timing</button><button onClick={()=>act(makeDraft,'Draft prepared — replace source footage with your own approved assets')}>Prepare four variants</button></>}</>}
      <details><summary>Imported asset identities</summary><pre>{JSON.stringify(data.assets,null,2)}</pre></details>
    </section>}
    {tab==='Plan'&&<section><h2>Four-variant plan</h2><p>Edit the planned assets, copy and declared changes before requesting a quote. Reuse only source footage you have permission to use.</p>
      <textarea aria-label="Experiment plan" rows={22} value={draft} onChange={e=>setDraft(e.target.value)}/><button onClick={()=>act(async()=>{const body=JSON.parse(draft);const r=await api.createExperiment(body) as Row;setExperiment(r.experiment.id);},'Experiment created')}>Save new experiment</button>
      {selected&&<><button onClick={()=>setDraft(JSON.stringify({segments:selected.experiment.packaging.segments,voice:selected.experiment.voice,music:selected.experiment.music,variants:selected.variants.filter((v:Row)=>v.variant_key!=='A').map((v:Row)=>({key:v.variant_key,factor:v.changed_factor,regions:v.allowed_regions,segments:v.segments,hypothesis:v.hypothesis,primary_metric:v.primary_metric,allowed_fields:v.allowed_fields,dependent_fields:v.dependent_fields})),reason:'Operator revision'},null,2))}>Load current draft</button>
      <button onClick={()=>act(()=>api.patchDraft(experimentId,JSON.parse(draft),selected.revision),'New revision saved; prepare a new quote')}>Save revised draft</button>
      <p>Selected revision {selected.revision} · {selected.status}</p><button onClick={()=>act(()=>api.quote(experimentId,selected.revision),'Quote queued')}>Prepare current quote</button>
      {plan&&<><pre>{JSON.stringify({plan_hash:plan.plan_hash,native_unit_totals:plan.total_price,work:plan.stats},null,2)}</pre><GenerationApproval plan={plan} selected={selected} budgets={data.budgets||[]} reviewer={reviewer} act={act}/></>}
      <button onClick={()=>act(()=>api.run(experimentId,selected.revision),'Production queued')}>Start / recover this revision</button></>}
    </section>}
    {tab==='Queue'&&<QueueScreen jobs={jobs.filter(j=>!experimentId||j.experiment_id===experimentId).map(j=>({id:j.id,variant:j.variant_key||'',stage:j.phase,state:(j.status==='succeeded'?'done':['failed','blocked'].includes(j.status)?j.status:j.status==='awaiting_review'?'blocked':['ready','waiting_dependencies'].includes(j.status)?'queued':'running') as JobView['state']}))}
      onRetry={id=>act(()=>call("POST",`/api/jobs/${id}/retry-local`,{body:{reviewer:requireReviewer()}}),"Local retry queued")} onRelease={id=>act(()=>call("POST",`/api/jobs/${id}/release-local`,{body:{reviewer:requireReviewer()}}),"Owned cleanup queued")} onPause={()=>act(()=>api.pause(experimentId))} onResume={()=>act(()=>api.resume(experimentId))} onReconcile={id=>act(()=>call('POST',`/api/jobs/${id}/reconcile`,{body:{}}))}/>}
    {tab==='Compare'&&<CompareScreen entries={compare}/>}
    {tab==='Reviews'&&<section><h2>Review assets and finals</h2>{plan&&<><p>Inspect the imported or generated picture assets before approving their use.</p>{videoAssets.map(a=><details key={a.id}><summary>{a.id}</summary><video controls src={media(a.id)} style={{maxHeight:300}}/><button onClick={()=>act(()=>call('POST',`/api/experiments/${experimentId}/assets/review`,{rev:selected?.revision,body:{plan_hash:plan.plan_hash,reviewer:requireReviewer(),artifact_ids:[a.id],verdict:'pass'}}))}>Accept this asset for this plan</button></details>)}</>}
      {finals.map(v=><ReviewsScreen key={v.id} target={{variant:v.variant_key,sha256:v.final.sha256,revision:v.experiment_revision,stale:!!v.stale_reason,failures:reviews.filter(r=>v.final.check_ids.includes(r.id)&&r.verdict!=='pass').map(r=>({check:r.check_type,detail:(r.limitations||[]).join(', ')}))}}
        onVerdict={(verdict,notes)=>act(()=>api.review(v.id,{check_type:'creative',verdict:verdict==='accept'?'pass':'fail',target_hash:v.final.sha256,reviewer:requireReviewer(),notes}))}/>)}
    </section>}
    {tab==='Delivery'&&<section><label>Configured Drive folder <input value={folder} onChange={e=>setFolder(e.target.value)}/></label><label>Drive account <input value={account} onChange={e=>setAccount(e.target.value)}/></label>
      {finals.map(v=><button key={v.id} onClick={()=>act(()=>api.deliver(v.id,{folder_id:folder,account,reviewer:requireReviewer(),valid_until:new Date(Date.now()+3600000).toISOString(),artifact_id:v.final.artifact_id,target_hash:v.final.sha256,
        check_ids:[...v.final.check_ids,...reviews.filter(r=>r.check_type==='creative'&&r.target_hash===v.final.sha256&&r.verdict==='pass').slice(0,1).map(r=>r.id)]},v.experiment_revision),'Delivery queued')}>Authorize delivery of {v.variant_key}</button>)}
      <DeliveryScreen items={(data.deliveries||[]).map(d=>({variant:d.variant_plan_id,status:d.status,link:d.drive_link,remote_md5:d.remote_md5,cleanup_state:d.cleanup_receipt?.startsWith('{')?JSON.parse(d.cleanup_receipt).state:'pending'}))}/>
    </section>}
    {tab==='Studio'&&<section><h2>Studio and revision feedback</h2><select aria-label="Studio variant" value={studioVariant} onChange={e=>setStudioVariant(e.target.value)}><option value="">Select rendered variant</option>{finals.map(v=><option key={v.id} value={v.id}>{v.variant_key}</option>)}</select>
      <button onClick={()=>act(async()=>{await call<Row>('POST',`/api/variants/${studioVariant}/studio`,{body:{},rev:selected?.revision});},'Studio requested')}>Open owned Studio</button>
      {studioSession?.url&&<a href={studioSession.url} target="_blank" rel="noreferrer">Open Studio workspace</a>}
      {studioSession&&<button onClick={()=>act(()=>call('POST',`/api/studio/${studioSession.session_id}/close`,{body:{}}))}>Close owned Studio</button>}
      <label>Time in seconds <input value={at} onChange={e=>setAt(e.target.value)}/></label><label>Proposed edit <textarea value={comment} onChange={e=>setComment(e.target.value)}/></label><button onClick={()=>act(()=>call('POST',`/api/variants/${studioVariant}/comments`,{rev:selected?.revision,body:{at_s:Number(at),text:comment}}),'Change proposed; no generation started')}>Save proposed change</button>
    </section>}
    {tab==='Providers'&&<ProvidersScreen providers={providers}/>}
    {['Products','Budgets','Research','Analysis','Audio','Publishing','Learning'].includes(tab)&&<OperationsScreen section={tab} data={data} selected={selected} reviewer={reviewer} act={act}/>}
    </fieldset>
  </main>;
}
