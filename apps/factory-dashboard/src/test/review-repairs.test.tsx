import React from 'react';
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {ResumeForm} from '../features/autorun/ResumeForm';
import {ManualPost, ManualMetrics} from '../features/publishing/ManualEvidence';
import * as client from '../api/client';
afterEach(() => {cleanup(); vi.restoreAllMocks();});
const act = (fn:()=>Promise<unknown>) => fn();

it('resumes with audited limits and a renewed expiry while retaining other limits', async () => {
  const resume = vi.spyOn(client.api, 'autorunResume').mockResolvedValue({});
  render(<ResumeForm run={{id:'run', pause:{at:'pause'}, params:{limits:{usd_micros:1000000,elevenlabs_credits:500}}}}
    units={['usd_micros','elevenlabs_credits']} budgetIds={['fund']} act={act}/>);
  fireEvent.change(screen.getByLabelText('Per-plan limit (USD)'), {target:{value:'2.5'}});
  fireEvent.change(screen.getByLabelText('New approval expiry (local time)'), {target:{value:'2099-01-01T12:00'}});
  fireEvent.submit(screen.getByRole('button',{name:'Resume with checked budgets'}).closest('form')!);
  await waitFor(() => expect(resume).toHaveBeenCalledWith('run', {pause_at:'pause',add_budget_ids:['fund'],
    set_params:{limits:{usd_micros:2500000,elevenlabs_credits:500},valid_until:new Date('2099-01-01T12:00').toISOString()}}));
});

it('registers a manual post against the selected exact final', async () => {
  const call=vi.spyOn(client,'call').mockResolvedValue({});
  render(<ManualPost variants={[{id:'exp:a',variant_key:'A',final:{artifact_id:'final',sha256:'hash'}}]}
    revision={2} reviewer="Operator" act={act}/>);
  fireEvent.change(screen.getByLabelText('Posted final'),{target:{value:'exp:a'}});
  fireEvent.change(screen.getByLabelText('Post account'),{target:{value:'account'}});
  fireEvent.change(screen.getByLabelText('Native post ID'),{target:{value:'post'}});
  fireEvent.change(screen.getByLabelText('Final verification evidence'),{target:{value:'Saved upload receipt'}});
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.submit(screen.getByRole('button',{name:'Verify and register existing post'}).closest('form')!);
  await waitFor(() => expect(call).toHaveBeenCalledWith('POST','/api/variants/exp:a/publications/manual',{
    rev:2,body:{artifact_id:'final',final_sha256:'hash',platform:'youtube',account_id:'account',remote_post_id:'post',reviewer:'Operator',evidence:'Saved upload receipt'}}));
});

it('manual metrics preserve zero and leave unobserved fields absent', async () => {
  const call=vi.spyOn(client,'call').mockResolvedValue({});
  render(<ManualMetrics publication={{id:'pub',platform:'youtube',published_at:'2026-09-10T09:00:00Z'}} reviewer="Operator" act={act}/>);
  fireEvent.change(screen.getByLabelText('Metric source'),{target:{value:'Studio'}});
  fireEvent.change(screen.getByLabelText('Metric evidence'),{target:{value:'Saved report'}});
  fireEvent.change(screen.getByLabelText('Measured at (local time)'),{target:{value:'2026-09-12T12:00'}});
  fireEvent.change(screen.getByLabelText('Views'),{target:{value:'0'}});
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.submit(screen.getByRole('button',{name:'Record verified manual metrics'}).closest('form')!);
  await waitFor(() => expect(call).toHaveBeenCalledWith('POST','/api/publications/pub/readbacks/manual',expect.objectContaining({body:expect.objectContaining({metrics:{views:0},horizon:'48h',reviewer:'Operator'})})));
});
