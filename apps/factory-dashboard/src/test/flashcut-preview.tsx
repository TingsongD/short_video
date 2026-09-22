// Inert browser walkthrough. No backend, credentials or billable actions.
import React,{useState} from 'react';
import {createRoot} from 'react-dom/client';
import {AutoRunScreen,RunProgress} from '../features/autorun/AutoRunScreen';
import {CompareScreen} from '../features/compare/CompareScreen';
import '../style.css';
const policies={version:1,variation:'full_video',captions:'phrases.v1',delivery:'after_qc',speech_repairs:2,overlay_repairs:2};
const states:Record<string,any>={
  Measuring:{status:'running',stage:'video_analysis',source_analysis:{stage:'visual',state:'processing',decoded_frames:300,encoded_frames:256,audio_status:'pending',jev_status:'pending'}},
  Waiting:{status:'running',stage:'video_analysis',source_analysis:{stage:'understanding',state:'waiting',decoded_frames:900,encoded_frames:900,total_frames:900,audio_status:'measured',processed_audio_samples:1440000,rhythm_status:'supported_candidates',event_count:48,cache_reused_chunks:4,jev_mode:'shadow',jev_status:'unknown_retained',repairs_used:1,clarifications_used:1,next_attempt_at:'2026-09-22T12:00:00Z',updated_at:'2026-09-22T11:59:50Z'}},
  Paused:{status:'paused',stage:'video_analysis',source_analysis:{stage:'visual',state:'paused',decoded_frames:512,encoded_frames:256,total_frames:900,repairs_used:2},pause:{code:'source_evidence_chunk_exhausted',detail:'Frames 256–511: two local recovery attempts exhausted.',action:'Repair the source file or local helper. Existing evidence is preserved; no paid request will be replayed.'}},
  Complete:{status:'succeeded',stage:'done',source_analysis:{stage:'complete',state:'complete',decoded_frames:900,encoded_frames:900,total_frames:900,audio_status:'measured',processed_audio_samples:1440000,rhythm_status:'supported_candidates',event_count:48,jev_mode:'shadow',jev_status:'complete'},state:{completion_phases:{generation:'complete',qc:'complete',delivery:'complete'}}}
};
function Preview(){const [selected,setSelected]=useState('Measuring');return <main>
  <h1>Offline flash-cut QA — no live actions</h1>
  <nav>{Object.keys(states).map(k=><button key={k} onClick={()=>setSelected(k)}>{k}</button>)}</nav>
  <RunProgress run={{id:'offline-fixture',params:{policies},...states[selected]}}/>
  <AutoRunScreen seeds={[]} budgets={[]} runs={[]} act={async()=>{}} media={()=>''} onSelectExperiment={()=>{}}/>
  <p>Playback-control fixture only: these four mock entries intentionally share one local test file; they are not live generated variants.</p>
  <CompareScreen entries={['A','B','C','D'].map(key=>({key,label:`${key} — offline native fixture`,
    media_url:'/qa-media/flashcut.mp4',state:'ready_for_review',duration_s:9,
    details:{changes:{factor:key==='A'?'control':'full_video',label:'Multi-variable creative comparison'},
      checks:[{check_type:'Fixture QC',verdict:'pass',reviewer:'offline-test'}]}}))}/>
  <h2>Local rendered fixture</h2><video controls preload="metadata" src="/qa-media/flashcut.mp4" style={{maxWidth:360,width:'100%'}}/>
</main>}
createRoot(document.getElementById('root')!).render(<Preview/>);
