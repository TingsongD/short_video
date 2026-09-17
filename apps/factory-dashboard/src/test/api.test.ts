import { beforeEach, describe, expect, it, vi } from "vitest";
import { api, session, ApiError } from "../api/client";

/** Client↔F27 contract: paths, headers, idempotency, revisions. */

const calls: { url: string; init: RequestInit }[] = [];

function fakeFetch(routes: Record<string, unknown>) {
  return vi.fn(async (url: any, init: any = {}) => {
    calls.push({ url: String(url), init });
    const key = `${init.method ?? "GET"} ${url}`;
    const body = routes[key] ?? routes[url] ?? { error: "not_found" };
    const ok = !("error" in (body as object));
    return new Response(JSON.stringify(body), {
      status: ok ? 200 : 409,
      headers: { "content-type": "application/json" },
    });
  }) as any;
}

beforeEach(() => {
  calls.length = 0;
});

describe("api client contract", () => {
  it("session issues a token used as CSRF", async () => {
    globalThis.fetch = fakeFetch({
      "POST /api/session": { session_token: "tok-1" },
      "GET /api/health": { api: "ok" },
    });
    await session();
    await api.health();
    expect(calls[0].url).toBe("/api/session");
  });

  it("mutations send idempotency-key + csrf + expected revision", async () => {
    globalThis.fetch = fakeFetch({
      "POST /api/session": { session_token: "tok-1" },
      "POST /api/experiments/e1/authorize": { ok: true },
    });
    await session();
    await api.authorize("e1", 3);
    const h = calls[1].init.headers as Record<string, string>;
    expect(h["idempotency-key"]).toMatch(/^ui-/);
    expect(h["x-csrf-token"]).toBe("tok-1");
    expect(h["x-expected-revision"]).toBe("3");
  });

  it("endpoints map to the versioned API surface", async () => {
    globalThis.fetch = fakeFetch({
      "GET /api/providers": {},
      "GET /api/seeds/s1": {},
      "POST /api/seeds": {},
      "POST /api/experiments": {},
      "PATCH /api/experiments/e1/draft": {},
      "POST /api/experiments/e1/quote": {},
      "POST /api/experiments/e1/run": {},
      "GET /api/experiments/e1/results": {},
    });
    await api.providers();
    await api.getSeed("s1");
    await api.createSeed("u");
    await api.createExperiment({ id: "e1" });
    await api.patchDraft("e1", {}, 0);
    await api.quote("e1");
    await api.run("e1", 0);
    await api.results("e1");
    expect(calls.map((c) => `${c.init.method ?? "GET"} ${c.url}`)).toEqual([
      "GET /api/providers",
      "GET /api/seeds/s1",
      "POST /api/seeds",
      "POST /api/experiments",
      "PATCH /api/experiments/e1/draft",
      "POST /api/experiments/e1/quote",
      "POST /api/experiments/e1/run",
      "GET /api/experiments/e1/results",
    ]);
  });

  it("409 stale_revision surfaces as a stale ApiError", async () => {
    globalThis.fetch = fakeFetch({
      "POST /api/session": { session_token: "t" },
      "POST /api/experiments/e1/authorize": {
        error: "stale_revision", field: "revision",
        detail: "expected 0, current 1",
      },
    });
    await session();
    const err = await api.authorize("e1", 0).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).stale).toBe(true);
    expect((err as ApiError).code).toBe("stale_revision");
  });
});

it("reuses one durable logical action across module reload and keeps revisions separate", async()=>{
  const first=await import('../api/client');
  const a=await first.actionKey('POST','/run',{x:1,y:2},1);
  vi.resetModules();
  const second=await import('../api/client');
  expect(await second.actionKey('POST','/run',{y:2,x:1},1)).toBe(a);
  expect(await second.actionKey('POST','/run',{x:1,y:2},2)).not.toBe(a);
});


it("retains uncertain retries but advances an acknowledged action",async()=>{
  const client=await import('../api/client');let count=0;const keys:string[]=[];
  globalThis.fetch=vi.fn(async(url:any,init:any)=>{
    if(url==='/api/session')return new Response(JSON.stringify({session_token:'fixture'}));
    keys.push(init.headers['idempotency-key']);count++;
    if(count===1)throw new Error('lost response');
    return new Response('{}');
  }) as any;
  await client.call('POST','/pause-recovery',{body:{}}).catch(()=>{});
  await client.call('POST','/pause-recovery',{body:{}});
  await client.call('POST','/pause-recovery',{body:{}});
  expect(keys[0]).toBe(keys[1]);expect(keys[2]).not.toBe(keys[1]);
});
