import React from 'react';
import {afterEach, expect, it, vi} from 'vitest';
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {AutoRunScreen, RunProgress} from '../features/autorun/AutoRunScreen';
import {OperationsScreen} from '../features/operations/OperationsScreen';
import {api} from '../api/client';

afterEach(() => {cleanup(); vi.restoreAllMocks();});

it('new dashboard launches opt into full-video phrases and bounded repairs', async () => {
  const launch = vi.spyOn(api, 'autorunCreate').mockResolvedValue({});
  render(<AutoRunScreen seeds={[{id:'source', evidence_status:'media_ready'}]}
    budgets={[{id:'qa-budget',unit:'usd_micros',available:100}]} runs={[]}
    media={()=>''} onSelectExperiment={()=>{}} act={async fn=>fn()}/>);
  expect(screen.getByLabelText('Footage variation')).toHaveValue('full_video');
  expect(screen.getByLabelText('Caption style')).toHaveValue('phrases.v1');
  expect(screen.getByText('Optional per-plan limits')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Or pick an existing seed'), {target:{value:'source'}});
  fireEvent.change(screen.getByLabelText('TTS voice id'), {target:{value:'voice'}});
  fireEvent.click(screen.getByLabelText(/qa-budget/));
  fireEvent.click(screen.getByText('Generate A–D automatically'));
  await waitFor(()=>expect(launch).toHaveBeenCalledOnce());
  expect(launch.mock.calls[0][0]).toMatchObject({policies:{version:1,variation:'full_video',captions:'phrases.v1',speech_repairs:2,overlay_repairs:2}});
  expect(launch.mock.calls[0][0].policies).not.toHaveProperty('delivery'); // Server resolves authorized destination.
});

it('separates QC/delivery and shows persisted repair exhaustion', () => {
  render(<RunProgress run={{id:'qa',stage:'final_qc',status:'paused',
    params:{policies:{variation:'full_video',captions:'phrases.v1',speech_repairs:2,overlay_repairs:2}},
    state:{completion_phases:{generation:'complete',qc:'complete',delivery:'running'},speech_repair_attempts:{'B:b1':2}},
    pause:{code:'delivery_unverified',detail:'Checksum unavailable',action:'Reconcile the existing upload; do not upload another copy.'}}}/>);
  expect(screen.getByLabelText('Completion phases')).toHaveTextContent('Generation: complete · QC: complete · Delivery: paused');
  expect(screen.getByText(/Narration B:b1: 2\/2/)).toBeTruthy();
  expect(screen.getByText(/Checksum unavailable/)).toBeTruthy();
  expect(screen.queryByText(/Finals verified on Drive/)).toBeNull();
});

it('does not describe local estimates or historical holds as confirmed charges', () => {
  render(<OperationsScreen section="Budgets" reviewer="" selected={null} act={async()=>{}}
    data={{budgets:[{id:'shared',unit:'usd_micros',estimated_usage:250000,confirmed_usage:0,unresolved_holds:750000}]}}/>);
  expect(screen.getByText('Provider-confirmed usage')).toBeTruthy();
  expect(screen.getByText('750000')).toBeTruthy();
  expect(screen.getByText(/Shared budget rows overlap/)).toBeTruthy();
});

it('shows run guardrails separately from reusable funding',()=>{
  render(<OperationsScreen section="Budgets" reviewer="" selected={null} act={async()=>{}}
    data={{budgets:[
      {id:'shared',unit:'usd_micros',classification:'reusable',selection_eligible:true,cap_amount:100},
      {id:'run_guardrail:auto-one:usd',unit:'usd_micros',classification:'run_guardrail',selection_eligible:false,cap_amount:50000000,available:38000000},
    ]}}/>);
  expect(screen.getByText('Reusable spending budgets').nextElementSibling).not.toHaveTextContent('run_guardrail:auto-one:usd');
  expect(screen.getByText('Per-run cumulative guardrails').nextElementSibling).toHaveTextContent('run_guardrail:auto-one:usd');
});

it('does not offer internal or retired ceilings as run funding',()=>{
  render(<AutoRunScreen seeds={[]} budgets={[
    {id:'funded',unit:'usd_micros',selection_eligible:true},
    {id:'authority:private',unit:'usd_micros',selection_eligible:false},
    {id:'retired',unit:'usd_micros',retired:true}]} runs={[]}
    media={()=>''} onSelectExperiment={()=>{}} act={async fn=>fn()}/>);
  expect(screen.getByLabelText(/funded/)).toBeTruthy();
  expect(screen.queryByText(/authority:private/)).toBeNull();
  expect(screen.queryByText(/retired/)).toBeNull();
});

it('explains and reports the isolated cumulative USD run guardrail',()=>{
  render(<AutoRunScreen seeds={[]} budgets={[]} runs={[]} act={async fn=>fn()}
    media={()=>''} onSelectExperiment={()=>{}}/>);
  expect(screen.getByText(/up to \$50 cumulative USD per new run/i)).toBeTruthy();
  cleanup();
  render(<RunProgress run={{id:'run',status:'running',stage:'video_analysis',
    spending_policy:{scope:'cumulative_run',unit:'usd_micros',cap_amount:50000000,
      committed:12000000,remaining:38000000}}}/>);
  expect(screen.getByLabelText('Run USD guardrail')).toHaveTextContent('$38.00 remaining of $50.00');
  expect(screen.getByLabelText('Run USD guardrail')).toHaveTextContent('holds and confirmed usage');
});
