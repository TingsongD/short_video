import React, {useState} from 'react';
import {api} from '../../api/client';

type Row = Record<string, any>;
export function ResumeForm({run, units, budgetIds, act}: {
  run: Row; units: string[]; budgetIds: string[];
  act: (fn: () => Promise<unknown>, message?: string) => Promise<unknown>;
}) {
  const [limits, setLimits] = useState<Record<string, string>>({});
  const [expiry, setExpiry] = useState('');
  const allUnits = [...new Set([...units, ...Object.keys(run.params?.limits || {})])];
  const factor = (unit: string) => unit === 'usd_micros' ? 1_000_000 : 1;
  const label = (unit: string) => unit === 'usd_micros' ? 'USD' : unit.replace(/_/g, ' ');
  return <form onSubmit={event => {event.preventDefault(); void act(async () => {
    const changes: Row = {};
    const supplied = Object.entries(limits).filter(([, value]) => value.trim());
    if (supplied.length) {
      changes.limits = {...(run.params?.limits || {})};
      for (const [unit, value] of supplied) {
        const amount = Number(value) * factor(unit);
        if (!Number.isSafeInteger(Math.round(amount)) || Math.abs(amount - Math.round(amount)) > .000001 || amount <= 0)
          throw new Error('Enter a positive amount in the displayed unit.');
        changes.limits[unit] = Math.round(amount);
      }
    }
    if (expiry) {
      const date = new Date(expiry);
      if (!Number.isFinite(date.getTime()) || date.getTime() <= Date.now()) throw new Error('Choose a future expiry.');
      changes.valid_until = date.toISOString();
    }
    return api.autorunResume(run.id, {pause_at: run.pause?.at,
      ...(budgetIds.length ? {add_budget_ids: budgetIds} : {}),
      ...(Object.keys(changes).length ? {set_params: changes} : {})});
  }, 'Run resumed');}}>
    <details><summary>Update limits or approval expiry</summary>
      <p>Changes are recorded with this resume. Blank fields keep the saved settings. The fixed total run cap stays in force.</p>
      {allUnits.map(unit => <label key={unit}>Per-plan limit ({label(unit)})
        <input type="number" min={1 / factor(unit)} step={1 / factor(unit)} value={limits[unit] || ''}
          placeholder={run.params?.limits?.[unit] ? String(run.params.limits[unit] / factor(unit)) : 'No additional limit'}
          onChange={event => setLimits({...limits, [unit]: event.target.value})}/></label>)}
      <p>Current approval expires: {run.params?.valid_until || 'Not set'}</p>
      <label>New approval expiry (local time)<input type="datetime-local" value={expiry} onChange={event => setExpiry(event.target.value)}/></label>
    </details>
    <button type="submit">Resume{budgetIds.length ? ' with checked budgets' : ''}</button>
  </form>;
}
