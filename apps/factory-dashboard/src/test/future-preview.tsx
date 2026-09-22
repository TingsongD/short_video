// Development-only, inert browser fixture. No backend calls or spending.
import React from 'react';
import {createRoot} from 'react-dom/client';
import {AutoRunScreen} from '../features/autorun/AutoRunScreen';
import {OperationsScreen} from '../features/operations/OperationsScreen';
import {ExternalDelivery} from '../features/delivery/DeliveryScreen';
import '../style.css';

const policies = {version:1,variation:'full_video',captions:'phrases.v1',delivery:'after_qc',speech_repairs:2,overlay_repairs:2};
createRoot(document.getElementById('root')!).render(<main>
  <h1>Offline QA fixture — no live actions</h1>
  <AutoRunScreen seeds={[]} budgets={[{id:'funded',unit:'usd_micros',available:1000000}, {id:'authority:internal',unit:'usd_micros',selection_eligible:false}]} media={()=>''} onSelectExperiment={()=>{}} act={async()=>{}}
    runs={[
      {id:'qa-repair',status:'paused',stage:'footage',params:{policies},
       state:{overlay_repair_attempts:{'B-clip-1':2},source_timing:{passages:[{quality:'passage_only',attempts:2}]}},
       pause:{code:'overlay_repair_exhausted',detail:'B clip 1: unwanted subtitles remain after two repairs.',action:'Replace or revise this clip, then Resume. No automatic repeat or shared footage substitution.'}},
      {id:'qa-delivered',status:'succeeded',stage:'done',params:{policies},
       state:{completion_phases:{generation:'complete',qc:'complete',delivery:'complete'}}}
    ]}/>
  <ExternalDelivery variant={{id:'fixture-A',variant_key:'A',final:{artifact_id:'fixture',sha256:'fixture'}}} revision={1} folder="fixture-folder" account="fixture-account" act={async()=>{}}/>
  <OperationsScreen section="Budgets" selected={null} reviewer="" act={async()=>{}}
    data={{budgets:[{id:'historical',unit:'usd_micros',cap_amount:1000000,available:0,pending_estimates:0,estimated_usage:250000,confirmed_usage:0,quoted_usage:0,unresolved_holds:750000}]}}/>
</main>);
