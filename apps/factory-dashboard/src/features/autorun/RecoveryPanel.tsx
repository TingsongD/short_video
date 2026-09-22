import React, { useState } from 'react';
import { api } from '../../api/client';

type Row = Record<string, any>;

export function RecoveryPanel({run, act}: {run:Row; act:(fn:()=>Promise<unknown>, message?:string)=>Promise<unknown>}) {
  const [reviewer,setReviewer]=useState('');
  const [evidence,setEvidence]=useState('');
  const [approve,setApprove]=useState(false);
  const r=run.recovery;
  if (!r) return null;
  const actions:string[]=r.actions||[];
  const reviewed=!!reviewer.trim()&&!!evidence.trim();
  const body={reviewer:reviewer.trim(),evidence:evidence.trim(),event_seq:r.event_seq};
  return <section className="recovery-card" aria-label="Analysis recovery">
    <h4>{r.title}</h4><p>{r.message}</p>
    {r.estimate?.usd_micros!=null&&<p>Previous request: ${(r.estimate.usd_micros/1000000).toFixed(2)} reserved estimate.
      This is not an invoice or a guaranteed price for a new request.</p>}
    {!actions.length&&!r.can_resume&&<p>No new request will be sent until the previous outcome is reconciled.</p>}
    {actions.some(a=>['recover_saved','settle_unusable','retry_analysis'].includes(a))&&<label>Recovery reviewer
      <input value={reviewer} onChange={e=>setReviewer(e.target.value)}/></label>}
    {(actions.includes('recover_saved')||actions.includes('settle_unusable'))&&<label>Recovery evidence
      <textarea value={evidence} onChange={e=>setEvidence(e.target.value)}
        placeholder="What you checked in the saved response and validation event"/></label>}
    {actions.includes('recover_saved')&&<button disabled={!reviewed}
      onClick={()=>act(()=>api.autorunRecoverAnalysis(run.id,body),'Saved response recovered locally. Review status before Resume.')}>
      Recover saved result — no new request</button>}
    {actions.includes('settle_unusable')&&<details><summary>Response cannot be recovered?</summary>
      <p>Account for the completed request at its reserved estimate. This does not retry, refund, or increase a budget.</p>
      <button disabled={!reviewed} onClick={()=>act(()=>api.reconcileInvalidAnalysis(r.attempt_id,body),'Completed analysis reconciled; no retry started.')}>
        Settle unusable response — no retry</button></details>}
    {actions.includes('retry_analysis')&&<>
      <label><input type="checkbox" checked={approve} onChange={e=>setApprove(e.target.checked)}/>
        I approve a new paid analysis within the existing budgets.</label>
      <button disabled={!approve||!reviewer.trim()} onClick={()=>act(()=>api.autorunResume(run.id,
        {pause_at:run.pause?.at,approve_paid_analysis_retry:true,reviewer:reviewer.trim(),
          analysis_attempt_id:r.attempt_id,analysis_event_seq:r.event_seq}),'Paid retry approved; readiness and budget checks still apply.')}>
        Approve paid analysis retry</button></>}
  </section>;
}
