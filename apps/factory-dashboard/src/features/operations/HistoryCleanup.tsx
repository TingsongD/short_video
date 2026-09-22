import React, { useState } from 'react';
import { call } from '../../api/client';

export interface HistoryItem {
  kind: 'job' | 'run';
  id: string;
  version_hash: string;
  status: string;
  eligible: boolean;
  archived: boolean;
}
export interface HistorySnapshot { items: HistoryItem[] }

export function HistoryCleanup({ history, showArchived, onShowArchived, onChanged, onResetSelection, disabled }: {
  history: HistorySnapshot | null;
  showArchived: boolean;
  onShowArchived: (show: boolean) => void;
  onChanged: () => Promise<void>;
  onResetSelection: () => void;
  disabled: boolean;
}) {
  const [preview, setPreview] = useState<{ action: 'archive' | 'restore'; snapshot: HistorySnapshot } | null>(null);
  const [busy, setBusy] = useState(false);
  const [resetSelection, setResetSelection] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const archived = history?.items.filter(i => i.archived).length || 0;
  const targets = preview?.snapshot.items.filter(i => preview.action === 'restore' ? i.archived : i.eligible && !i.archived) || [];
  const jobs = targets.filter(i => i.kind === 'job').length;
  const runs = targets.filter(i => i.kind === 'run').length;
  const countLabel = `${jobs} ${jobs === 1 ? 'job' : 'jobs'} and ${runs} ${runs === 1 ? 'run' : 'runs'}`;

  async function open(action: 'archive' | 'restore') {
    setBusy(true); setError(''); setNotice(''); setResetSelection(false);
    try { setPreview({ action, snapshot: await call<HistorySnapshot>('GET', '/api/dashboard/history') }); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!preview) return;
    setBusy(true); setError('');
    try {
      if (targets.length) await call('POST', '/api/dashboard/history', {
        body: { action: preview.action, targets: targets.map(({kind, id, version_hash}) => ({kind, id, version_hash})) },
      });
      if (preview.action === 'archive' && resetSelection) onResetSelection();
      setPreview(null);
      setNotice(`${preview.action === 'archive' ? 'Archived' : 'Restored'} ${countLabel}. Nothing was deleted.`);
      await onChanged();
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  return <section className="history-cleanup" aria-label="Dashboard cleanup">
    <fieldset disabled={disabled || busy}>
      <button disabled={!history} onClick={() => open('archive')}>Clean up</button>
      <label><input type="checkbox" checked={showArchived} onChange={e => onShowArchived(e.target.checked)}/>
        Show archived ({archived})</label>
      {archived > 0 && <button onClick={() => open('restore')}>Restore archived history</button>}
      {busy && <span role="status">Updating dashboard history…</span>}
      {preview && <div className="cleanup-preview" role="region" aria-label="Cleanup preview">
        <h2>{preview.action === 'archive' ? 'Archive past jobs' : 'Restore archived history'}</h2>
        <p>{countLabel} will be {preview.action === 'archive' ? 'hidden from' : 'shown in'} Queue and Auto across this dashboard, regardless of the selected experiment.</p>
        <p>Active, paused and unresolved work stays visible. Videos, source files, approvals and spending records are kept. Archiving does not cancel or restart anything.</p>
        <details><summary>Preview affected history ({targets.length})</summary>
          <ul>{targets.map(i => <li key={`${i.kind}:${i.id}`}>{i.kind}: {i.id} · {i.status}</li>)}</ul>
        </details>
        {preview.action === 'archive' && <label><input type="checkbox" checked={resetSelection} onChange={e => setResetSelection(e.target.checked)}/>
          Reset saved experiment selection and refresh dashboard data (not media or generation caches)</label>}
        <button disabled={!targets.length && !(preview.action === 'archive' && resetSelection)} onClick={confirm}>
          {preview.action === 'archive' ? 'Confirm cleanup' : 'Confirm restore'}</button>
        <button onClick={() => setPreview(null)}>Cancel</button>
      </div>}
    </fieldset>
    {error && <p role="alert">{error}</p>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
