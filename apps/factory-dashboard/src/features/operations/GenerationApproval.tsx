import React,{useState} from 'react';
import {call} from '../../api/client';
type Row=Record<string,any>;
export function GenerationApproval({plan,selected,budgets,reviewer,act}:{plan:Row;selected:Row;budgets:Row[];reviewer:string;act:(fn:()=>Promise<unknown>,message?:string)=>Promise<unknown>}){
 const [account,setAccount]=useState(''),[budget,setBudget]=useState('');
 const totals=plan.total_price||{};const funded=Object.keys(totals).length>0;
 const policy=selected.experiment.provider_policy;
 return <section aria-label="Generation approval">
  {funded&&<><p>Approve only these displayed provider totals. An updated plan needs a new approval.</p><label>Provider account<input value={account} onChange={e=>setAccount(e.target.value)}/></label><label>Funded generation budget<select value={budget} onChange={e=>setBudget(e.target.value)}><option value="">Choose budget</option>{budgets.filter(b=>!b.retired&&!b.id.startsWith('authority:')&&b.unit in totals).map(b=><option key={b.id}>{b.id}</option>)}</select></label></>}
  <button onClick={()=>act(()=>{if(!reviewer.trim())throw new Error('Enter your reviewer name first.');return call('POST',`/api/experiments/${plan.experiment_id}/authorize`,{rev:selected.revision,body:{plan_hash:plan.plan_hash,reviewer:reviewer.trim(),...(funded?{ceilings:totals,account,budget_ids:[budget],allowed_providers:Object.keys(policy.allowed_models),allowed_models:policy.allowed_models,valid_until:new Date(Date.now()+3600000).toISOString()}: {})}});},'Plan approved')}>{funded?'Approve displayed generation quote':'Approve imported-media plan'}</button>
 </section>;
}
