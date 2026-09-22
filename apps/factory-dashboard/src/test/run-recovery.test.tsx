import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { RecoveryPanel } from '../features/autorun/RecoveryPanel';
import { api } from '../api/client';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const run = {id:'r', pause:{at:'now'}, recovery:{kind:'response_invalid',
  title:'Analysis returned, but failed validation', message:'Recover saved response first.',
  attempt_id:'att', event_seq:7, estimate:{usd_micros:250000}, actions:['recover_saved','settle_unusable']}};
const act = (fn:()=>Promise<unknown>) => fn();

it('local recovery requires review and never resumes paid work', async () => {
  const recover=vi.spyOn(api,'autorunRecoverAnalysis').mockResolvedValue({});
  const resume=vi.spyOn(api,'autorunResume').mockResolvedValue({});
  render(<RecoveryPanel run={run} act={act}/>);
  expect(screen.getByRole('button',{name:'Recover saved result — no new request'})).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Recovery reviewer'),{target:{value:'Operator'}});
  fireEvent.change(screen.getByLabelText('Recovery evidence'),{target:{value:'Reviewed saved response'}});
  fireEvent.click(screen.getByRole('button',{name:'Recover saved result — no new request'}));
  await waitFor(()=>expect(recover).toHaveBeenCalledWith('r',expect.objectContaining({event_seq:7,reviewer:'Operator'})));
  expect(resume).not.toHaveBeenCalled();
  expect(screen.getByText(/\$0.25/)).toBeTruthy();
});

it('an unknown outcome has no retry control', () => {
  render(<RecoveryPanel run={{...run,recovery:{kind:'outcome_unknown',title:'Outcome unknown',message:'Reconcile first',actions:[]}}} act={act}/>);
  expect(screen.queryByRole('button')).toBeNull();
  expect(screen.getByText(/No new request will be sent/)).toBeTruthy();
});

it('paid retry is separate and requires an explicit checkbox', async () => {
  const resume=vi.spyOn(api,'autorunResume').mockResolvedValue({});
  render(<RecoveryPanel run={{...run,recovery:{...run.recovery,actions:['retry_analysis']}}} act={act}/>);
  fireEvent.change(screen.getByLabelText('Recovery reviewer'),{target:{value:'Operator'}});
  expect(screen.getByRole('button',{name:'Approve paid analysis retry'})).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox'));
  fireEvent.click(screen.getByRole('button',{name:'Approve paid analysis retry'}));
  await waitFor(()=>expect(resume).toHaveBeenCalledWith('r',expect.objectContaining({approve_paid_analysis_retry:true,
    analysis_attempt_id:'att',analysis_event_seq:7})));
});
