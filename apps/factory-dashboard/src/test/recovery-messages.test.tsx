import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { RunProgress } from "../features/autorun/AutoRunScreen";
import { ProvidersScreen } from "../features/providers/ProvidersScreen";

afterEach(cleanup);
it.each([
  ["reauth_required", /Reconnect the configured Google account/],
  ["credential_transport_failed", /network/],
  ["credential_dependency_missing", /Google authentication dependencies/],
  ["loader_failed", /does not prove whether a request was sent/],
])("explains %s in the paused run without promising a refund", (reason, message) => {
  render(<RunProgress run={{ id: "r", status: "paused", stage: "video_analysis",
    pause: { code: "analysis_failed", detail: `job j: ${reason}`, action: "Resolve failing job" } }} />);
  expect(screen.getByText(message)).toBeTruthy();
  expect(screen.getByText(/Reconcile any unknown attempt before Resume/)).toBeTruthy();
});
it("shows Google auth recovery for analysis, not a budget instruction", () => {
  render(<ProvidersScreen providers={{ audiovisual_analysis: {
    installed: true, authenticated: false, catalog_visible: true, tested: true,
    qualified: true, detail: { reason: "reauth_required" },
  } }} />);
  expect(screen.getByText(/Reconnect the configured Google account/)).toBeTruthy();
  expect(screen.queryByText(/Set Google budget/)).toBeNull();
});

it.each(["malformed_analysis", "invalid_analysis_timing"])(
  "explains %s as potentially billable without offering a free retry", (reason) => {
    render(<RunProgress run={{ id: "r", status: "paused", stage: "video_analysis",
      pause: { code: "analysis_failed", detail: `job j: ${reason}`, action: "Resolve failing job" } }} />);
    expect(screen.getByText(/potentially billable/)).toBeTruthy();
    expect(screen.getByText(/settle its estimate before Resume/)).toBeTruthy();
    expect(screen.queryByText(/Reconnect the configured Google/)).toBeNull();
  });
