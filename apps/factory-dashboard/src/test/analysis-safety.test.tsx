import React from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { render, fireEvent, screen, waitFor, cleanup, act as flush } from '@testing-library/react';
import { AnalysisScreen } from '../features/analysis/AnalysisScreen';
import { api } from '../api/client';

afterEach(() => {cleanup(); vi.restoreAllMocks();});

it('cannot save the old source while the next source is loading', async () => {
  let finish!: (v: any) => void;
  vi.spyOn(api, 'getAnalysis').mockImplementation(async (id) => id === 'a'
    ? {seed_id:'a', revision:1, edit_token:'a-token', understanding:{premise:'Source A'}}
    : new Promise(resolve => {finish = resolve;}));
  const save = vi.spyOn(api, 'saveAnalysis').mockResolvedValue({});
  render(<AnalysisScreen seeds={[{id:'a'},{id:'b'}]} blueprints={[]} reviewer="qa"
    act={async fn => fn()} media={id => id}/>);
  fireEvent.change(screen.getByLabelText('Analysis source'), {target:{value:'a'}});
  await screen.findByDisplayValue('Source A');
  fireEvent.change(screen.getByLabelText('Analysis source'), {target:{value:'b'}});
  expect(screen.queryByDisplayValue('Source A')).not.toBeInTheDocument();
  expect(screen.queryByText('Save understanding')).not.toBeInTheDocument();
  finish({seed_id:'b', revision:1, edit_token:'b-token', understanding:{premise:'Source B'}});
  await screen.findByDisplayValue('Source B');
  fireEvent.click(screen.getByText('Save understanding'));
  await waitFor(() => expect(save).toHaveBeenCalledWith('b', 'understanding',
    expect.objectContaining({premise:'Source B',edit_token:'b-token'})));
});

it('discards a late response and keeps unsaved edits during background refresh', async () => {
  let old!: (value:any)=>void;
  let revision=1;
  vi.spyOn(api,'getAnalysis').mockImplementation(async id=>id==='a'
    ? new Promise(resolve=>{old=resolve;})
    : {seed_id:'b',revision,edit_token:'b-'+revision,status:'in_progress',understanding:{premise:'Source B '+revision}});
  const save=vi.spyOn(api,'saveAnalysis').mockResolvedValue({});
  render(<AnalysisScreen seeds={[{id:'a'},{id:'b'}]} blueprints={[]} reviewer="qa" act={async fn=>fn()} media={id=>id}/>);
  fireEvent.change(screen.getByLabelText('Analysis source'),{target:{value:'a'}});
  fireEvent.change(screen.getByLabelText('Analysis source'),{target:{value:'b'}});
  await screen.findByDisplayValue('Source B 1');
  await flush(async()=>old({edit_token:'a',understanding:{premise:'Late source A'}}));
  expect(screen.queryByDisplayValue('Late source A')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Premise — what is this video, in one line?'),{target:{value:'Unsaved edit'}});
  revision=2;
  fireEvent(document,new Event('visibilitychange'));
  await screen.findByText(/New analysis is available/);
  expect(screen.getByDisplayValue('Unsaved edit')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Save understanding'));
  await waitFor(()=>expect(save).toHaveBeenCalledWith('b','understanding',expect.objectContaining({premise:'Unsaved edit',edit_token:'b-1'})));
});
