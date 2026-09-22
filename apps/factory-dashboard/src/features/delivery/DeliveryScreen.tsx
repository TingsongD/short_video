import React, {useState} from "react";
import {call} from '../../api/client';
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

export function ExternalDelivery({variant,revision,folder,account,act}:{variant:Record<string,any>;revision:number;folder:string;account:string;act:(fn:()=>Promise<unknown>,message?:string)=>Promise<unknown>}) {
  const [file,setFile]=useState(''),[name,setName]=useState('');
  return <details><summary>Verify an existing Drive file for {variant.variant_key}</summary>
    <p>Checks the current final against this exact file. Does not upload or grant creative approval.</p>
    <label>Drive file ID<input value={file} onChange={e=>setFile(e.target.value)}/></label>
    <label>Exact remote filename<input value={name} onChange={e=>setName(e.target.value)}/></label>
    <button disabled={!file.trim()||!name.trim()||!folder||!account} onClick={()=>act(()=>call('POST',`/api/variants/${variant.id}/delivery/reconcile`,{
      rev:revision,body:{file_id:file.trim(),name:name.trim(),folder_id:folder,account,
        artifact_id:variant.final.artifact_id,target_hash:variant.final.sha256}}),'Verification queued — no upload requested')}>Verify existing file</button>
  </details>;
}
