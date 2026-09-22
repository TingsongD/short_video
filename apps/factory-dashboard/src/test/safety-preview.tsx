// Inert development fixture: all API and event traffic terminates in memory.
import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import App from '../App';
import {AnalysisScreen} from '../features/analysis/AnalysisScreen';
import {CompareScreen} from '../features/compare/CompareScreen';
import {QueueScreen, queueJobView} from '../features/queue/QueueScreen';
import {PublishingScreen} from '../features/publishing/PublishingScreen';
import '../style.css';

const revisions:Record<string,number> = {a:1,b:1};
const request = window.fetch.bind(window);
window.fetch = async (input, init) => {
  const path = String(input).split('?')[0];
  if (!path.startsWith('/api/')) return request(input, init);
  const reply = (body:unknown,status=200) => new Response(JSON.stringify(body),{status});
  if (path === '/api/session') return reply({session_token:'offline-only'});
  if (init?.method && !['GET','HEAD'].includes(init.method)) return reply({error:'offline_fixture_read_only'},405);
  if (path === '/api/health') return reply({api:'ok',mode:'offline',worker:{available:true}});
  if (path === '/api/providers') return reply({});
  if (path === '/api/studio/sessions') return reply({items:[]});
  if (path === '/api/collections/queue') return reply({items:{jobs:[]}});
  if (path === '/api/collections/products') return reply({error:'fixture_resource_unavailable'},503);
  if (path.startsWith('/api/collections/')) return reply({items:[]});
  if (path.startsWith('/api/analysis/')) {
    const id = path.split('/').pop()!;
    await new Promise(resolve=>setTimeout(resolve,id==='a'?900:80));
    return reply({seed_id:id,status:'in_progress',revision:revisions[id],edit_token:id+revisions[id],
      understanding:{premise:`Source ${id.toUpperCase()} revision ${revisions[id]}`}});
  }
  return reply({error:'not_found'},404);
};
class InertEvents {addEventListener(){} close(){}}
window.EventSource = InertEvents as unknown as typeof EventSource;
window.localStorage.setItem('selected-experiment','deleted-fixture');
window.localStorage.setItem('qa-preserve','yes');
function Preview() {
  const [status,setStatus] = useState('scheduled');
  const noop = async () => {};
  return <main><h1>Offline safety QA — no live actions</h1>
    <details><summary>Dashboard with deleted selection and one unavailable collection</summary><App/></details>
    <button onClick={()=>{revisions.b++; document.dispatchEvent(new Event('visibilitychange'));}}>Simulate newer analysis</button>
    <AnalysisScreen seeds={[{id:'a'},{id:'b'}]} blueprints={[]} reviewer="Offline QA" act={noop} media={()=>''}/>
    <QueueScreen jobs={[queueJobView({id:'analysis-fixture',phase:'analyze',status:'ready',blocked_reason:'analysis_throttled',next_attempt_at:'2026-09-22T00:00:00Z'}), queueJobView({id:'retry-fixture',phase:'collect',status:'ready',blocked_reason:'retry_backoff',next_attempt_at:'2026-09-22T00:01:00Z'})]}/>
    <CompareScreen entries={['A','B','C','D'].map(key=>({key,label:key+' — offline fixture',duration_s:4,details:{changes:{label:'Multi-variable creative comparison'}}}))}/>
    <button onClick={()=>setStatus('cancelled')}>Simulate cancellation refresh</button>
    <PublishingScreen selected={{id:'fixture-exp',revision:1,variants:[{id:'fixture:A',variant_key:'A'}]}}
      data={{publications:[{id:'fixture-publication',variant_plan_id:'fixture:A',platform:'youtube',status}]}}
      reviewer="Offline QA" act={noop}/>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Preview/>);
