import React from "react";
import type { ProviderReadiness } from "../../api/client";
import { Blocked, Empty, Loading } from "../../components/States";

/** Granular readiness — installed/authenticated/catalog/tested/
 * qualified are separate truths; operator-language actions. */
export function ProvidersScreen(
  { providers }: { providers: Record<string, ProviderReadiness> | undefined },
) {
  if (providers === undefined) return <Loading what="providers" />;
  const names = Object.keys(providers);
  if (names.length === 0)
    return <Empty what="providers" hint="Run provider doctor first." />;

  return (
    <section aria-label="providers">
      <h2>Providers</h2>
      <ul>
        {names.map((name) => {
          const p = providers[name];
          const blocked = !p.installed
            ? `${name} is not installed`
            : !p.authenticated
              ? `Reconnect ${name === "vertex" ? "Google" : "Jimeng"}`
              : !p.qualified
                ? `${name} is not qualified for this mode`
                : null;
          return (
            <li key={name}>
              <strong>{name}</strong>
              <ul aria-label={`${name} readiness`}>
                <li>installed: {String(p.installed)}</li>
                <li>authenticated: {String(p.authenticated)}</li>
                <li>catalog visible: {String(p.catalog_visible)}</li>
                <li>tested: {String(p.tested)}</li>
                <li>qualified: {String(p.qualified)}</li>
              </ul>
              {blocked
                ? <Blocked why={blocked}
                           action={name === "vertex"
                             ? "Set Google budget to enable Vertex."
                             : "Re-run connection check."} />
                : <span>Ready</span>}
              <p>Provider changes require a revised plan and a new quote.</p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
