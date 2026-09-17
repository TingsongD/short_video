import React from "react";
import { Blocked } from "../../components/States";

export interface DeliveryView {
  variant: string;
  status: "pending" | "uploaded" | "verified" | "conflict" | "failed";
  link?: string;
  remote_md5?: string;
  cleanup_state?: "verified" | "blocked" | "pending";
  problems?: string[];
}

/** Verified Drive links + cleanup receipts; blocked actions explain
 * themselves; technical IDs stay behind details. */
export function DeliveryScreen({ items }: { items: DeliveryView[] }) {
  return (
    <section aria-label="delivery">
      <h2>Delivery</h2>
      <ul>
        {items.map((d) => (
          <li key={d.variant}>
            <strong>{d.variant}</strong>:{" "}
            {d.status === "verified"
              ? <>Upload verified —{" "}
                  <a href={d.link} target="_blank" rel="noreferrer">
                    open in Drive</a></>
              : d.status === "conflict"
                ? <Blocked why="A different file already uses this name"
                           action="Rename the revision — the remote
                             file was not touched." />
                : d.status === "failed"
                  ? <Blocked why="Upload failed"
                             action="Retry transfer — the local final
                               is kept." />
                  : <span>Waiting — {d.status}</span>}
            {d.cleanup_state && (
              <span> · cleanup {d.cleanup_state}</span>)}
            {d.problems?.length ? (
              <details>
                <summary>details</summary>
                <ul>{d.problems.map((p) => <li key={p}>{p}</li>)}</ul>
              </details>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
