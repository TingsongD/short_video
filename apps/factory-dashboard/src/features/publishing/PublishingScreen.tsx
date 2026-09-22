import React,{useEffect,useState} from 'react';
import {call} from '../../api/client';
type Row=Record<string,any>;
type Props={data:Record<string,Row[]>;selected:Row|null;reviewer:string;act:(fn:()=>Promise<unknown>,message?:string)=>Promise<unknown>};
const expires=()=>new Date(Date.now()+3600000).toISOString();
const PLATFORMS=['youtube','tiktok','instagram','facebook'] as const;

/** PL-03/PL-04/PL-10: metadata packages, 16-slot publication matrix,
 * per-destination status/identity, remote-schedule cancellation and
 * checkpoint observation state — all honestly labelled. */
export function PublishingScreen({data,selected,reviewer,act}:Props){
  const [accounts,setAccounts]=useState<Record<string,string>>({youtube:'',tiktok:'',instagram:'',facebook:''});
  const [enabled,setEnabled]=useState<Record<string,boolean>>({youtube:true,tiktok:false,instagram:false,facebook:false});
  const [publicationId,setPublicationId]=useState<string|null>(null);
  const [pkg,setPkg]=useState<Row|null>(null);
  const [context,setContext]=useState('');
  const eid=selected?.experiment?.experiment_id||selected?.id,rev=selected?.revision;
  const variants=(selected?.variants||[]) as Row[];
  const finals=variants.filter(v=>v.final);
  const pubs=(data.publications||[]) as Row[];
  const publication=pubs.find(p=>p.id===publicationId && variants.some(v=>v.id===p.variant_plan_id));
  useEffect(()=>{setPublicationId(null);setPkg(null);},[eid]);
  const packages=(data.metadatapackages||[]) as Row[];
  const checkpoints=(data.checkpoints||[]) as Row[];
  function reviewed(){if(!reviewer.trim())throw new Error('Enter your reviewer name first.');return reviewer.trim();}
  const post=(path:string,body:Row={},revision?:number)=>call<Row>('POST',path,{body,rev:revision});
  const put=(path:string,body:Row={},revision?:number)=>call<Row>('PUT',path,{body,rev:revision});
  const destinations=PLATFORMS.filter(p=>enabled[p]&&accounts[p].trim()).map(p=>({platform:p,account_id:accounts[p].trim()}));
  const slotFor=(variantId:string,platform:string)=>pubs.find(p=>p.variant_plan_id===variantId&&p.platform===platform);
  const slotStatus=(p:Row|undefined)=>{if(!p)return '—';
    if(p.status==='scheduled')return 'scheduled_remote — will publish unless cancelled';
    if(p.status==='public')return `public · ${p.remote_post_id||''}`;
    if(p.status==='cancelled')return 'cancelled';
    return p.status||'unknown';};
  const pkgFor=(variantId:string,platform:string)=>packages.find(m=>m.variant_plan_id===variantId&&m.platform===platform);
  const cpsFor=(pid:string)=>checkpoints.filter(c=>c.publication_id===pid);
  // The opened package follows the latest collection row — mutations
  // bump the row `version` CAS handle, so a stale snapshot would 409.
  const livePkg=pkg?(packages.find(m=>m.id===pkg.id)||pkg):null;
  return <section><h2>Publishing</h2>
    <p>Metadata packages are reviewed and frozen per destination before planning. Each slot below is an independent durable intent — a partial failure never blocks the others.</p>
    <h3>Destinations</h3>
    {PLATFORMS.map(p=><label key={p} style={{display:'inline-block',marginRight:12}}><input type="checkbox" checked={enabled[p]} onChange={e=>setEnabled({...enabled,[p]:e.target.checked})}/> {p} <input placeholder="account id" value={accounts[p]} onChange={e=>setAccounts({...accounts,[p]:e.target.value})}/></label>)}
    <h3>Metadata packages</h3>
    <label>Creative context for candidates<input value={context} onChange={e=>setContext(e.target.value)} placeholder="seed title / treatment / hypothesis"/></label>
    <table><thead><tr><th>Variant</th>{PLATFORMS.filter(p=>enabled[p]).map(p=><th key={p}>{p}</th>)}</tr></thead><tbody>
      {finals.map(v=><tr key={v.id}><td>{v.variant_key}</td>
        {PLATFORMS.filter(p=>enabled[p]).map(p=>{const m=pkgFor(v.id,p);return <td key={p}>
          {m?<button onClick={()=>setPkg(m)}>{m.status} · r{m.revision}</button>
            :<button onClick={()=>act(()=>post(`/api/variants/${v.id}/metadata`,{platform:p,final_sha256:v.final.sha256,context:{seed_title:context||v.variant_key,hypothesis:v.hypothesis||''}}),'Metadata draft created')}>Draft</button>}
        </td>;})}
      </tr>)}
    </tbody></table>
    {livePkg&&<details open><summary>Package {livePkg.id} — {livePkg.platform} ({livePkg.status})</summary>
      <pre>{JSON.stringify(livePkg.candidates,null,2)}</pre>
      <p>Disclosures: {JSON.stringify(livePkg.disclosures||{})}</p>
      {livePkg.status==='draft'&&livePkg.candidates.map((c:Row)=><button key={c.id} onClick={()=>act(()=>put(`/api/metadata/${livePkg.id}/select`,{candidate_id:c.id,reviewer:reviewed()},livePkg.version),'Candidate selected')}>Select {c.id}</button>)}
      {livePkg.status==='selected'&&<button onClick={()=>act(()=>post(`/api/metadata/${livePkg.id}/freeze`,{},livePkg.version),'Package frozen')}>Freeze package</button>}
    </details>}
    <h3>Publication matrix</h3>
    <button disabled={!destinations.length} onClick={()=>act(()=>post(`/api/experiments/${eid}/publications`,{reviewer:reviewed(),destinations},rev),'Publication batch planned')}>Plan {finals.length}×{destinations.length} batch</button>
    <table><thead><tr><th>Variant</th>{PLATFORMS.map(p=><th key={p}>{p}</th>)}</tr></thead><tbody>
      {variants.map(v=><tr key={v.id}><td>{v.variant_key}</td>
        {PLATFORMS.map(p=>{const s=slotFor(v.id,p);return <td key={p} title={s?.id||''}>{slotStatus(s)}{s&&<button onClick={()=>setPublicationId(s.id)}>open</button>}</td>;})}
      </tr>)}
    </tbody></table>
    {publication&&<details open><summary>Publication {publication.id}</summary>
      <pre>{JSON.stringify({platform:publication.platform,account:publication.account_id,status:publication.status,provider:publication.provider,post:publication.remote_post_id,url:publication.post_url,scheduled_at:publication.scheduled_at,published_at:publication.published_at,job:publication.job_id,metadata_package:publication.metadata_package_id},null,2)}</pre>
      <button onClick={()=>act(()=>post(`/api/publications/${publication.id}/authorize`,{final_sha256:publication.final_sha256,platform:publication.platform,account_id:publication.account_id,action:'publish',reviewer:reviewed(),valid_until:expires()}),'Exact publication approved')}>Authorize this slot</button>
      <button onClick={()=>act(()=>post(`/api/publications/${publication.id}/run`),'Publication queued')}>Publish approved slot</button>
      <button onClick={()=>act(()=>post(`/api/publications/${publication.id}/observe`),'Status check queued')}>Refresh remote status</button>
      {publication.status==='scheduled'&&<button onClick={()=>act(()=>post(`/api/publications/${publication.id}/cancel-remote`),'Remote cancellation requested')}>Cancel remote schedule</button>}
      {publication.status==='scheduled'&&<p>This post is scheduled with the provider — pausing local work will NOT stop it going live. Cancel it explicitly.</p>}
      {cpsFor(publication.id).length>0&&<><h4>Observation checkpoints</h4><table><thead><tr><th>Horizon</th><th>Due</th><th>Status</th></tr></thead><tbody>{cpsFor(publication.id).map(c=><tr key={c.id}><td>{c.horizon}</td><td>{c.due_at}</td><td>{c.status}</td></tr>)}</tbody></table></>}
    </details>}
  </section>;
}
