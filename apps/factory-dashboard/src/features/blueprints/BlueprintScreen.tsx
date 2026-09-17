import React from "react";
import { RevisionBadge } from "../../components/States";

export interface Beat {
  id: string;
  label: string;
  start_s: number;
  end_s: number;
  script: string;
}

export interface Blueprint {
  id: string;
  revision: number;
  status: string;
  beats: Beat[];
}

export interface VariantPlan {
  key: "A" | "B" | "C" | "D";
  factor: string;
  regions: { start_s: number; end_s: number }[];
  locked: boolean;
}

/** Blueprint timeline + A/B/C/D planner: synchronized script/timing
 * comparison, immutable revision badges, locked fields and a readable
 * "what changes" summary per treatment. */
export function BlueprintScreen(
  { blueprint, plans }: { blueprint: Blueprint; plans: VariantPlan[] },
) {
  return (
    <section aria-label="blueprint">
      <h2>
        Blueprint {blueprint.id} <RevisionBadge rev={blueprint.revision} />
      </h2>
      <p>status: {blueprint.status}</p>
      <table>
        <thead>
          <tr><th>beat</th><th>time</th><th>script</th>
              {plans.map((p) => <th key={p.key}>{p.key}</th>)}
          </tr>
        </thead>
        <tbody>
          {blueprint.beats.map((b) => (
            <tr key={b.id}>
              <td>{b.label}</td>
              <td>{b.start_s}–{b.end_s}s</td>
              <td>{b.script}</td>
              {plans.map((p) => {
                const changed = p.regions.some(
                  (r) => b.start_s < r.end_s && b.end_s > r.start_s);
                return (
                  <td key={p.key} aria-label={
                    changed ? `${p.key} changes ${b.label}` : undefined}>
                    {changed ? p.factor : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <h3>What changes</h3>
      <ul>
        {plans.map((p) => (
          <li key={p.key}>
            <strong>{p.key}</strong>: {p.factor}{" "}
            {p.regions.map((r) => `${r.start_s}–${r.end_s}s`).join(", ")}
            {p.locked && <span> (locked — new revision required)</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
