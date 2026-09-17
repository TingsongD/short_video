import React, { useEffect, useState } from "react";
import { api, ProviderReadiness, session } from "./api/client";
import { SeedsScreen, SeedView } from "./features/seeds/SeedsScreen";
import { ProductsScreen, ProductView } from "./features/products/ProductsScreen";
import { BlueprintScreen, Blueprint, VariantPlan } from "./features/blueprints/BlueprintScreen";
import { PlannerScreen } from "./features/experiments/PlannerScreen";
import { ProvidersScreen } from "./features/providers/ProvidersScreen";
import { BudgetsScreen, BudgetView } from "./features/budgets/BudgetsScreen";

const TABS = ["seeds", "products", "blueprint", "planner", "providers",
              "budgets"] as const;

export default function App() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("seeds");
  const [providers, setProviders] =
    useState<Record<string, ProviderReadiness>>();
  const [ready, setReady] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    session().then(() => setReady(true))
      .then(() => api.providers())
      .then(setProviders)
      .catch(() => setOffline(true));
  }, []);

  const seeds: SeedView[] = [];
  const products: ProductView[] = [];
  const blueprint: Blueprint = {
    id: "bp-demo", revision: 0, status: "draft", beats: [],
  };
  const plans: VariantPlan[] = [];
  const budgets: BudgetView[] = [];

  return (
    <main>
      <h1>Viral Video Factory</h1>
      {offline &&
        <p role="alert">API offline — start the local service.</p>}
      <nav aria-label="screens">
        {TABS.map((t) => (
          <button key={t} onClick={() => setTab(t)}
                  aria-current={tab === t ? "page" : undefined}>
            {t}
          </button>
        ))}
      </nav>
      {tab === "seeds" && <SeedsScreen seeds={seeds} />}
      {tab === "products" && <ProductsScreen products={products} />}
      {tab === "blueprint" &&
        <BlueprintScreen blueprint={blueprint} plans={plans} />}
      {tab === "planner" && <PlannerScreen experimentId="exp-current" />}
      {tab === "providers" && <ProvidersScreen providers={providers} />}
      {tab === "budgets" && <BudgetsScreen budgets={budgets} />}
    </main>
  );
}
