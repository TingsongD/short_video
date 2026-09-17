import React from "react";
import { Empty, Loading } from "../../components/States";

export interface BudgetView {
  unit: "credits" | "usd_micros";
  ceiling: number | null;
  reserved: number;
  used: number;
  unknown: number;
  repair_scope: string;
}

/** Independent credit/USD ceilings with reserves, usage, unknown
 * charges and repair/fallback scope — unknown is never a zero. */
export function BudgetsScreen(
  { budgets }: { budgets: BudgetView[] | undefined },
) {
  if (budgets === undefined) return <Loading what="budgets" />;
  if (budgets.length === 0)
    return <Empty what="budgets" hint="Set ceilings before quoting." />;
  return (
    <section aria-label="budgets">
      <h2>Budgets</h2>
      <table>
        <thead>
          <tr><th>unit</th><th>ceiling</th><th>reserved</th>
              <th>used</th><th>unknown</th><th>repair scope</th></tr>
        </thead>
        <tbody>
          {budgets.map((b) => (
            <tr key={b.unit}>
              <td>{b.unit === "credits" ? "credits" : "USD"}</td>
              <td>{b.ceiling === null ? "not set" : b.ceiling}</td>
              <td>{b.reserved}</td>
              <td>{b.used}</td>
              <td>{b.unknown > 0 ? `${b.unknown} unknown` : "—"}</td>
              <td>{b.repair_scope}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
