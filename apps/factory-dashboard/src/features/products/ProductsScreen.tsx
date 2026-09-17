import React, { useState } from "react";
import { Empty, Loading } from "../../components/States";

export interface ProductView {
  id: string;
  title: string;
  snapshot_at: string;
  angles: string[];
  media: { id: string; kind: string; available: boolean }[];
  facts: string[];
}

/** Multi-product/variant selection: snapshot dates, available angles
 * and media, supported factual copy, unavailable assets — and never
 * a Shopify credential. */
export function ProductsScreen(
  { products }: { products: ProductView[] | undefined },
) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  if (products === undefined) return <Loading what="products" />;
  if (products.length === 0)
    return <Empty what="products"
                  hint="Run a catalog snapshot from the ops panel." />;

  function toggle(id: string) {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else if (n.size < 3) n.add(id);   // up to three products/variants
      return n;
    });
  }

  return (
    <section aria-label="products">
      <h2>Products</h2>
      <p>Select up to three products for this experiment.</p>
      <ul>
        {products.map((p) => (
          <li key={p.id}>
            <label>
              <input type="checkbox"
                     checked={selected.has(p.id)}
                     onChange={() => toggle(p.id)}
                     aria-label={`select ${p.title}`} />
              {p.title}
            </label>
            <span className="snapshot"> snapshot {p.snapshot_at}</span>
            <ul>
              {p.angles.map((a) => <li key={a}>angle: {a}</li>)}
              {p.media.map((m) => (
                <li key={m.id}>
                  {m.kind} {m.available ? "✓" : "— unavailable"}
                </li>
              ))}
              {p.facts.map((f) => <li key={f}>copy: “{f}”</li>)}
            </ul>
          </li>
        ))}
      </ul>
      <output aria-label="selection count">
        {selected.size} selected
      </output>
    </section>
  );
}
