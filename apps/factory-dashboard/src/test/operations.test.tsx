import React from 'react';
import {beforeEach,expect,it,vi} from 'vitest';
import {render,screen,fireEvent,waitFor} from '@testing-library/react';
import {OperationsScreen} from '../features/operations/OperationsScreen';
import {GenerationApproval} from '../features/operations/GenerationApproval';
import {call} from '../api/client';
vi.mock('../api/client',()=>({call:vi.fn(async()=>({}))}));
beforeEach(()=>vi.mocked(call).mockClear());
const act=async(fn:()=>Promise<unknown>)=>fn();
it('records an explicit native-unit budget with the required scope',async()=>{
 render(<OperationsScreen section="Budgets" data={{}} selected={null} reviewer="Operator" act={act}/>);
 fireEvent.change(screen.getByLabelText('Budget name'),{target:{value:'voice-budget'}});
 fireEvent.change(screen.getByLabelText('Unit'),{target:{value:'elevenlabs_credits'}});
 fireEvent.change(screen.getByLabelText('Ceiling in this unit'),{target:{value:'50'}});
 fireEvent.click(screen.getByText('Record spending ceiling'));
 await waitFor(()=>expect(call).toHaveBeenCalledWith('POST','/api/budgets',expect.objectContaining({body:expect.objectContaining({unit:'elevenlabs_credits',scope:'aggregate',scope_key:'',ceiling:50,reviewer:'Operator'})})));
});
it('generation approval binds selected revision, model, account, quote and funding',async()=>{
 render(<GenerationApproval plan={{experiment_id:'real-exp',plan_hash:'hash',total_price:{jimeng_credits:20}}} selected={{revision:4,experiment:{provider_policy:{allowed_models:{jimeng_canvas:['pinned-model']}}}}} budgets={[{id:'approved',unit:'jimeng_credits'}]} reviewer="Operator" act={act}/>);
 fireEvent.change(screen.getByLabelText('Provider account'),{target:{value:'account-123'}});
 fireEvent.change(screen.getByLabelText('Funded generation budget'),{target:{value:'approved'}});
 fireEvent.click(screen.getByText('Approve displayed generation quote'));
 await waitFor(()=>expect(call).toHaveBeenCalledWith('POST','/api/experiments/real-exp/authorize',expect.objectContaining({rev:4,body:expect.objectContaining({account:'account-123',ceilings:{jimeng_credits:20},budget_ids:['approved'],allowed_models:{jimeng_canvas:['pinned-model']},plan_hash:'hash'})})));
});
it('freezes the supported metric and per-variant exposure before publication',async()=>{
 render(<OperationsScreen section="Learning" data={{}} selected={{revision:3,experiment:{experiment_id:'actual'}}} reviewer="Operator" act={act}/>);
 fireEvent.click(screen.getByText('Freeze policy before publication'));
 await waitFor(()=>expect(call).toHaveBeenCalledWith('POST','/api/experiments/actual/policy',expect.objectContaining({rev:3,body:expect.objectContaining({primary_metric:'thumbnail_ctr',exposure_metric:'thumbnail_impressions',min_exposure:1000,horizon:'48h'})})));
});
