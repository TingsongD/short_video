import React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { SeedsScreen } from "../features/seeds/SeedsScreen";
import { ProductsScreen } from "../features/products/ProductsScreen";
import { BlueprintScreen } from "../features/blueprints/BlueprintScreen";
import { ProvidersScreen } from "../features/providers/ProvidersScreen";
import { BudgetsScreen } from "../features/budgets/BudgetsScreen";
import { PlannerScreen } from "../features/experiments/PlannerScreen";
import { remoteOf } from "../components/States";

const calls: { url: string; init: any }[] = [];
function fakeFetch(routes: Record<string, unknown>) {
  return vi.fn(async (url: any, init: any = {}) => {
    calls.push({ url: String(url), init });
    const key = `${init.method ?? "GET"} ${url}`;
    const body = routes[key] ?? routes[url] ?? { error: "not_found" };
    return new Response(JSON.stringify(body), {
      status: "error" in (body as object) ? 409 : 200,
    });
  }) as any;
}

beforeEach(() => { calls.length = 0; });

describe("component states", () => {
  it("remoteOf covers loading/empty/ready/error", () => {
    expect(remoteOf(undefined, null).state).toBe("loading");
    expect(remoteOf([], null).state).toBe("empty");
    expect(remoteOf([1], null).state).toBe("ready");
    expect(remoteOf(undefined, new Error("x")).state).toBe("error");
  });

  it("seeds screen shows loading and empty states", () => {
    const { rerender } = render(<SeedsScreen seeds={undefined} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading seeds");
    rerender(<SeedsScreen seeds={[]} />);
    expect(screen.getByText(/No seeds yet/)).toBeInTheDocument();
  });

  it("seeds screen shows both ratios and unavailable-video guidance", () => {
    render(<SeedsScreen seeds={[{
      id: "s1", canonical_url: "u", status: "needs_source_media",
      outlier_ratio: 3.2, baseline_ratio: 1.1, observed_at: "2026-09-17",
      cohort_size: 50, confidence: "high",
    }]} />);
    expect(screen.getByText("outlier ×3.2")).toBeInTheDocument();
    expect(screen.getByText("cohort baseline ×1.1")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Source video unavailable");
    expect(screen.getByText(/cohort 50 · confidence high/))
      .toBeInTheDocument();
  });

  it("missing metrics render as pending, never as zero", () => {
    render(<SeedsScreen seeds={[{
      id: "s2", canonical_url: "u", status: "ready",
    }]} />);
    expect(screen.getByText("Outlier evidence pending"))
      .toBeInTheDocument();
    expect(screen.queryByText(/×0/)).not.toBeInTheDocument();
  });

  it("products screen enforces three-product cap and lists unavailability", () => {
    const products = [1, 2, 3, 4].map((i) => ({
      id: `p${i}`, title: `Product ${i}`, snapshot_at: "2026-09-17",
      angles: ["front"], media: [{ id: "m", kind: "video", available: i !== 2 }],
      facts: ["handmade"],
    }));
    render(<ProductsScreen products={products} />);
    for (const t of ["Product 1", "Product 2", "Product 3", "Product 4"]) {
      fireEvent.click(screen.getByLabelText(`select ${t}`));
    }
    expect(screen.getByLabelText("selection count"))
      .toHaveTextContent("3 selected");
    expect(screen.getByText(/— unavailable/)).toBeInTheDocument();
  });

  it("blueprint shows revision badge, changed beats and lock note", () => {
    render(<BlueprintScreen
      blueprint={{ id: "bp1", revision: 3, status: "accepted", beats: [
        { id: "b1", label: "hook", start_s: 0, end_s: 4, script: "hi" },
        { id: "b2", label: "body", start_s: 4, end_s: 10, script: "ok" },
      ] }}
      plans={[
        { key: "A", factor: "control", regions: [], locked: false },
        { key: "B", factor: "new hook", regions: [{ start_s: 0, end_s: 4 }],
          locked: true },
      ]} />);
    expect(screen.getByLabelText("revision 3")).toHaveTextContent("r3");
    expect(screen.getByLabelText("B changes hook"))
      .toHaveTextContent("new hook");
    expect(screen.getByText(/locked — new revision required/))
      .toBeInTheDocument();
  });

  it("providers screen separates readiness truths with operator language", () => {
    render(<ProvidersScreen providers={{
      vertex: { installed: true, authenticated: false,
                catalog_visible: false, tested: false, qualified: false },
      jimeng: { installed: true, authenticated: true,
                catalog_visible: true, tested: true, qualified: true },
    }} />);
    expect(screen.getByRole("alert"))
      .toHaveTextContent("Reconnect Google");
    expect(screen.getByText(/Set Google budget/))
      .toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
  });

  it("budgets screen shows unknown charges distinctly from zero", () => {
    render(<BudgetsScreen budgets={[
      { unit: "credits", ceiling: 50, reserved: 4, used: 8, unknown: 0,
        repair_scope: "bounded" },
      { unit: "usd_micros", ceiling: null, reserved: 0, used: 0,
        unknown: 2, repair_scope: "none" },
    ]} />);
    expect(screen.getByText("not set")).toBeInTheDocument();
    expect(screen.getByText("2 unknown")).toBeInTheDocument();
  });
});

describe("planner revision flow", () => {
  const routes = {
    "POST /api/session": { session_token: "t" },
    "POST /api/experiments/e1/quote": {
      quote: { experiment_id: "e1", revision: 2,
               units: { credits: 4, usd_micros: 900 },
               unknown_charges: [], line_items: [
                 { label: "picture A", credits: 2 },
                 { label: "speech", usd_micros: 900 }] } },
    "POST /api/experiments/e1/authorize": { ok: true },
    "POST /api/experiments/e1/run": { run: { job_id: "job-e1" } },
  };

  it("quote→approve→run binds the quoted revision", async () => {
    globalThis.fetch = fakeFetch(routes);
    render(<PlannerScreen experimentId="e1" />);
    fireEvent.click(screen.getByText("Get quote"));
    await screen.findByText("total: 4 credits, $0.00");
    fireEvent.click(screen.getByText("Approve this revision"));
    await screen.findByText("Approved r2");
    await waitFor(() => expect(screen.getByText("Run")).toBeEnabled());
    fireEvent.click(screen.getByText("Run"));
    await screen.findByText("Started job-e1");
    const revs = calls.map((c) =>
      (c.init.headers as any)["x-expected-revision"]);
    expect(revs).toEqual([undefined, "2", "2"]);
  });

  it("stale authorize shows an actionable conflict, not a crash", async () => {
    globalThis.fetch = fakeFetch({
      ...routes,
      "POST /api/experiments/e1/authorize": {
        error: "stale_revision", detail: "expected 0, current 1" },
    });
    render(<PlannerScreen experimentId="e1" />);
    fireEvent.click(screen.getByText("Get quote"));
    await screen.findByText(/total: 4 credits/);
    fireEvent.click(screen.getByText("Approve this revision"));
    await screen.findByRole("alert");
    expect(screen.getByRole("alert"))
      .toHaveTextContent("Re-quote the current revision");
    expect(screen.getByText("Run")).toBeDisabled();
  });

  it("double-click issues a single request (idempotent UI)", async () => {
    globalThis.fetch = fakeFetch(routes);
    render(<PlannerScreen experimentId="e1" />);
    const btn = screen.getByText("Get quote");
    fireEvent.click(btn);
    fireEvent.click(btn);   // busy guard swallows the second click
    await screen.findByText(/total: 4 credits/);
    expect(calls.filter((c) => c.url.includes("/quote"))).toHaveLength(1);
  });
});
