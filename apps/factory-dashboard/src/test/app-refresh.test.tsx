import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, fireEvent, screen } from "@testing-library/react";

import App from "../App";

const NAMES = ["seeds","blueprints","templates","experiments","plans","assets","reviews","deliveries","products","budgets","research","effect_plans","publications","metrics","policies","decisions","metadatapackages","checkpoints","selections","lineages","loops","autoruns","reservations"];

class FakeEventSource {
  static last: FakeEventSource | undefined;
  url: string;
  handlers: Record<string, (ev: { lastEventId: string; data: string }) => void> = {};
  constructor(url: string) {
    this.url = url;
    FakeEventSource.last = this;
  }
  addEventListener(type: string, fn: (ev: { lastEventId: string; data: string }) => void) {
    this.handlers[type] = fn;
  }
  close() {}
  emit(seq: number, type='tick') {
    this.handlers.factory?.({
      lastEventId: String(seq),
      data: JSON.stringify({ type, body: { seq } }),
    });
  }
}

describe("App live refresh", () => {
  const urls: string[] = [];

  beforeEach(() => {
    window.localStorage.clear();
    Object.defineProperty(document, 'visibilityState', {configurable:true, value:'visible'});
    urls.length = 0;
    FakeEventSource.last = undefined;
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      urls.push(String(url).split("?")[0]);
      const path = String(url).split("?")[0];
      if (path === "/api/session")
        return new Response(JSON.stringify({ session_token: "tok" }));
      if (path === "/api/health")
        return new Response(JSON.stringify({
          api: "ok", mode: "live",
          worker: { available: true },
        }));
      if (path === "/api/providers")
        return new Response(JSON.stringify({}));
      if (path === "/api/studio/sessions")
        return new Response(JSON.stringify({ items: [] }));
      if (path === "/api/collections/queue")
        return new Response(JSON.stringify({ items: { jobs: [] } }));
      if (path.startsWith("/api/collections/"))
        return new Response(JSON.stringify({ items: [] }));
      return new Response(JSON.stringify({ error: "not_found" }), { status: 404 });
    }));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('clears a deleted selection without losing healthy data or event updates', async () => {
    vi.useFakeTimers();
    window.localStorage.setItem('selected-experiment', 'deleted');
    render(<App/>);
    await act(async () => {await vi.advanceTimersByTimeAsync(600);});
    expect(window.localStorage.getItem('selected-experiment')).toBe('');
    expect(FakeEventSource.last).toBeTruthy();
    expect(screen.getByText(/Last checked/)).toBeTruthy();
  });

  it("does not issue one collection sweep per replayed event", async () => {
    vi.useFakeTimers();
    render(<App />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(FakeEventSource.last).toBeTruthy();
    const seedsBefore = urls.filter((u) => u === "/api/collections/seeds").length;
    expect(seedsBefore).toBeGreaterThanOrEqual(1);
    expect(urls).not.toContain('/api/collections/reservations');
    expect(urls).not.toContain('/api/collections/publications');

    const es = FakeEventSource.last!;
    await act(async () => {
      for (let seq = 1; seq <= 80; seq++) es.emit(seq);
      await vi.advanceTimersByTimeAsync(250);
    });
    const seedsAfter = urls.filter((u) => u === "/api/collections/seeds").length;
    expect(seedsAfter).toBe(seedsBefore + 1);
    expect(seedsAfter).toBeLessThan(10);
  });

  it('does not poll an idle dashboard every five seconds or while hidden', async () => {
    vi.useFakeTimers();
    render(<App />);
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    const initial = urls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(urls.length).toBe(initial);
    Object.defineProperty(document, 'visibilityState', {configurable:true, value:'hidden'});
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(60000); });
    expect(urls.length).toBe(initial);
    Object.defineProperty(document, 'visibilityState', {configurable:true, value:'visible'});
    await act(async () => { document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(300); });
    expect(urls.length).toBeGreaterThan(initial);
  });

  it('coalesces waiting events into status-only refreshes',async()=>{
    vi.useFakeTimers();render(<App/>);
    await act(async()=>{await vi.advanceTimersByTimeAsync(300);});
    const before=urls.filter(u=>u==='/api/collections/seeds').length;
    const status=urls.filter(u=>u==='/api/collections/autoruns').length;
    await act(async()=>{
      for(let i=1;i<=80;i++)FakeEventSource.last!.emit(i,'command_waiting');
      await vi.advanceTimersByTimeAsync(300);
    });
    expect(urls.filter(u=>u==='/api/collections/autoruns').length).toBe(status+1);
    expect(urls.filter(u=>u==='/api/collections/seeds').length).toBe(before);
  });

  it('refreshes active status without fetching detail collections every five seconds', async () => {
    vi.useFakeTimers();
    const original = globalThis.fetch;
    vi.stubGlobal('fetch', vi.fn(async (...args: Parameters<typeof fetch>) => {
      if(args[0]==='/api/collections/autoruns') {
        urls.push(String(args[0]));
        return new Response(JSON.stringify({items:[{id:'r',status:'running',stage:'footage'}]}));
      }
      return original(...args);
    }));
    render(<App/>);
    await act(async () => {await vi.advanceTimersByTimeAsync(300);});
    const status = urls.filter(u=>u==='/api/collections/autoruns').length;
    const details = urls.filter(u=>u==='/api/collections/seeds').length;
    await act(async () => {await vi.advanceTimersByTimeAsync(11000);});
    expect(urls.filter(u=>u==='/api/collections/autoruns').length).toBe(status+2);
    expect(urls.filter(u=>u==='/api/collections/seeds').length).toBe(details);
  });

  it('deduplicates slow requests and discards results after experiment selection changes', async () => {
    vi.useFakeTimers();
    window.localStorage.setItem('selected-experiment','old');
    let resolveOld!: (response:Response)=>void;
    let pending = false;
    const original = globalThis.fetch;
    vi.stubGlobal('fetch', vi.fn(async (...args:Parameters<typeof fetch>) => {
      const path = String(args[0]);
      if(path==='/api/collections/experiments') return new Response(JSON.stringify({items:[{id:'old-r1',experiment_id:'old',revision:1},{id:'new-r2',experiment_id:'new',revision:2}]}));
      if(path.includes('/results')) {
        urls.push(path);
        if(pending && path.includes('/old/')) return new Promise<Response>(resolve=>{resolveOld=resolve;});
        return new Response(JSON.stringify({revision:path.includes('/old/')?1:2,status:'draft',experiment:{},variants:[]}));
      }
      return original(...args);
    }));
    render(<App/>);
    await act(async()=>{await vi.advanceTimersByTimeAsync(300);});
    fireEvent.click(screen.getByRole('button',{name:'Plan'}));
    await act(async()=>{await vi.advanceTimersByTimeAsync(300);});
    expect(screen.getByText('Selected revision 1 · draft')).toBeTruthy();
    pending=true;
    await act(async()=>{FakeEventSource.last!.emit(1);await vi.advanceTimersByTimeAsync(300);});
    const requests=urls.filter(u=>u.includes('/old/results')).length;
    await act(async()=>{for(let i=2;i<30;i++)FakeEventSource.last!.emit(i);await vi.advanceTimersByTimeAsync(500);});
    expect(urls.filter(u=>u.includes('/old/results')).length).toBe(requests);
    fireEvent.change(screen.getByRole('combobox',{name:'Experiment'}),{target:{value:'new'}});
    await act(async()=>{await vi.advanceTimersByTimeAsync(300);});
    expect(screen.queryByText('Selected revision 1 · draft')).toBeNull();
    await act(async()=>{resolveOld(new Response(JSON.stringify({revision:99,experiment:{},variants:[]})));});
    expect(screen.queryByText(/Selected revision 99/)).toBeNull();
    expect(screen.getByText('Selected revision 2 · draft')).toBeTruthy();
  });
});
