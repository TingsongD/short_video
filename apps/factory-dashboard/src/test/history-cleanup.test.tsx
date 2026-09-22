import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from '../App';
import { HistoryItem } from '../features/operations/HistoryCleanup';

let history: HistoryItem[];
let posts: { action: string; targets: HistoryItem[] }[];
let reject = false;

beforeEach(() => {
  window.localStorage.clear();
  history = [
    {kind:'job',id:'old-job',version_hash:'v1',status:'succeeded',eligible:true,archived:false},
    {kind:'run',id:'old-run',version_hash:'v1',status:'succeeded',eligible:true,archived:false},
    {kind:'job',id:'paused-job',version_hash:'v1',status:'blocked',eligible:false,archived:false},
    {kind:'run',id:'paused-run',version_hash:'v1',status:'paused',eligible:false,archived:false},
  ];
  posts = []; reject = false;
  vi.stubGlobal('EventSource', class {addEventListener() {} close() {}});
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), {status});
    if (url === '/api/session') return response({session_token:'test'});
    if (url === '/api/health') return response({mode:'offline',worker:{available:true}});
    if (url.startsWith('/api/providers')) return response({});
    if (url.includes('/results')) return response({experiment:{},variants:[]});
    if (url === '/api/dashboard/history') {
      if (init.method === 'POST') {
        const body = JSON.parse(String(init.body)); posts.push(body);
        if (reject) return response({error:'stale_revision',detail:'Work changed since the preview. Reopen Clean up to refresh it; nothing was hidden.'},409);
        history = history.map(i => body.targets.some((t: HistoryItem) => t.id === i.id) ? {...i,archived:body.action === 'archive'} : i);
        return response({action:body.action});
      }
      return response({items:history});
    }
    if (url === '/api/collections/queue') return response({items:{history:{items:history}, jobs:history.filter(i=>i.kind==='job').map(i=>({...i,phase:'render',experiment_id:''}))}});
    if (url === '/api/collections/autoruns') return response({items:history.filter(i=>i.kind==='run').map(i=>({...i,created_at:i.id==='paused-run'?'2026-09-20':'2026-09-19',stage:i.status==='paused'?'blueprint':'done',progress:[]}))});
    return response({items:[]});
  }));
});
afterEach(() => {cleanup();vi.unstubAllGlobals();});

it('previews before archiving, keeps paused work visible, persists on reload and restores without retries', async () => {
  const view = render(<App/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Clean up'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Clean up'}));
  const preview = await screen.findByRole('region',{name:'Cleanup preview'});
  expect(within(preview).getByText(/1 job and 1 run/)).toBeInTheDocument();
  expect(posts).toHaveLength(0);
  fireEvent.click(within(preview).getByRole('button',{name:'Confirm cleanup'}));
  await screen.findByText(/Archived 1 job and 1 run/);
  fireEvent.click(screen.getByRole('button',{name:'Queue'}));
  await waitFor(()=>expect(screen.queryByText('old-job')).not.toBeInTheDocument());
  expect(screen.getByText('paused-job')).toBeInTheDocument();
  expect(screen.getByRole('region',{name:'Latest run status'})).toHaveTextContent('paused-run');
  view.unmount(); render(<App/>);
  await screen.findByRole('button',{name:'Restore archived history'});
  fireEvent.click(screen.getByRole('button',{name:'Auto'}));
  expect(screen.queryByText('old-run',{selector:'strong'})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox',{name:/Show archived/}));
  expect(screen.getByText('old-run',{selector:'strong'})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Restore archived history'}));
  fireEvent.click(await screen.findByRole('button',{name:'Confirm restore'}));
  await screen.findByText(/Restored 1 job and 1 run/);
  await waitFor(()=>expect(screen.queryByRole('button',{name:'Restore archived history'})).not.toBeInTheDocument());
  expect(posts.map(p=>p.action)).toEqual(['archive','restore']);
  expect(posts.flatMap(p=>p.targets).every(t=>t.id.startsWith('old-'))).toBe(true);
});

it('only clears the saved selection, preserving request identities and event cursor', async () => {
  window.localStorage.setItem('selected-experiment','old-experiment');
  window.localStorage.setItem('factory-action:pending','do-not-repeat');
  window.localStorage.setItem('factory-events:factory','1234');
  render(<App/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Clean up'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Clean up'}));
  fireEvent.click(await screen.findByRole('checkbox',{name:/Reset saved experiment selection/}));
  fireEvent.click(screen.getByRole('button',{name:'Confirm cleanup'}));
  await screen.findByText(/Archived 1 job and 1 run/);
  expect(window.localStorage.getItem('selected-experiment') || '').toBe('');
  expect(window.localStorage.getItem('factory-action:pending')).toBe('do-not-repeat');
  expect(window.localStorage.getItem('factory-events:factory')).toBe('1234');
});

it('cancel is read-only and stale confirmation reports a recoverable error', async () => {
  render(<App/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Clean up'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Clean up'}));
  fireEvent.click(await screen.findByRole('button',{name:'Cancel'}));
  expect(posts).toHaveLength(0);
  reject = true;
  fireEvent.click(screen.getByRole('button',{name:'Clean up'}));
  fireEvent.click(await screen.findByRole('button',{name:'Confirm cleanup'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('nothing was hidden');
  expect(screen.getByRole('region',{name:'Cleanup preview'})).toBeInTheDocument();
  expect(history.some(i=>i.archived)).toBe(false);
});
