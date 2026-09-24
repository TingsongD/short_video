import React, {useState} from 'react';
import {call} from '../../api/client';
type Row = Record<string, any>;
type Act = (fn: () => Promise<unknown>, message?: string) => Promise<unknown>;
const HOURS: Record<string, number> = {'24h':24, '48h':48, '72h':72, '7d':168, '28d':672};

export function ManualPost({variants, revision, reviewer, act}: {variants: Row[]; revision: number; reviewer: string; act: Act}) {
  const [variantId, setVariant] = useState('');
  const [platform, setPlatform] = useState('youtube');
  const [account, setAccount] = useState('');
  const [postId, setPost] = useState('');
  const [evidence, setEvidence] = useState('');
  const variant = variants.find(v => v.id === variantId);
  return <details><summary>Register a post published manually</summary>
    <p>Choose the final you posted. Registration checks the public post and account without uploading anything. Freeze the experiment’s learning policy and approve the final first.</p>
    <form onSubmit={e => {e.preventDefault(); void act(async () => {
      if (!reviewer.trim() || !variant) throw new Error('Choose a final and enter your reviewer name.');
      return call('POST', `/api/variants/${variant.id}/publications/manual`, {rev: revision, body: {
        artifact_id: variant.final.artifact_id, final_sha256: variant.final.sha256,
        platform, account_id: account.trim(), remote_post_id: postId.trim(), reviewer: reviewer.trim(), evidence: evidence.trim()}});
    }, 'Manual post registered and verified');}}>
      <label>Posted final<select required value={variantId} onChange={e => setVariant(e.target.value)}><option value="">Choose final</option>
        {variants.map(v => <option key={v.id} value={v.id}>{v.variant_key}</option>)}</select></label>
      <label>Post platform<select value={platform} onChange={e => setPlatform(e.target.value)}>{['youtube','tiktok','instagram','facebook'].map(p => <option key={p}>{p}</option>)}</select></label>
      <label>Post account<input required value={account} onChange={e => setAccount(e.target.value)}/></label>
      <label>Native post ID<input required value={postId} onChange={e => setPost(e.target.value)}/></label>
      <label>Final verification evidence<input required value={evidence} onChange={e => setEvidence(e.target.value)} placeholder="Post link and evidence that it uses this final"/></label>
      <label><input required type="checkbox"/>I confirm this post uses the selected final.</label>
      <button type="submit">Verify and register existing post</button>
    </form>
  </details>;
}

export function ManualMetrics({publication, reviewer, act}: {publication: Row; reviewer: string; act: Act}) {
  const [horizon, setHorizon] = useState('48h');
  const [source, setSource] = useState('');
  const [evidence, setEvidence] = useState('');
  const [measured, setMeasured] = useState('');
  const [metrics, setMetrics] = useState<Record<string, string>>({});
  const kind = publication.platform === 'youtube' ? 'exact_rolling' : 'observed_lifetime_at_age';
  const start = publication.published_at;
  const date = new Date(start);
  const end = Number.isFinite(date.getTime()) ? new Date(date.getTime() + HOURS[horizon] * 3600000).toISOString() : '';
  const fields = {views:'Views', likes:'Likes', comments:'Comments', shares:'Shares', avg_view_duration_s:'Average view duration (seconds)', avg_view_pct:'Average viewed (percent)',
    ...(['instagram', 'facebook'].includes(publication.platform) ? {reach:'Reach'} : {}),
    ...(publication.platform === 'youtube' ? {thumbnail_impressions:'Thumbnail impressions', thumbnail_ctr:'Thumbnail click rate (percent)', subs_gained:'Subscribers gained', engaged_views:'Engaged views'} : {saves:'Saves'})};
  return <details><summary>Import verified manual metrics</summary>
    <p>Enter only measured values. Blank means unavailable, not zero. Use the same source and units for every variant.</p>
    <form onSubmit={e => {e.preventDefault(); void act(async () => {
      if (!reviewer.trim()) throw new Error('Enter your reviewer name first.');
      const values = Object.fromEntries(Object.entries(metrics).filter(([, value]) => value.trim()).map(([key, value]) => [key, Number(value)]));
      if (!Object.keys(values).length) throw new Error('Enter at least one measured metric.');
      return call('POST', `/api/publications/${publication.id}/readbacks/manual`, {body: {horizon, metrics: values,
        period: {start, end, window_kind: kind}, observed_at: new Date(measured).toISOString(),
        source_name: source.trim(), evidence: evidence.trim(), reviewer: reviewer.trim()}});
    }, 'Manual metrics recorded with verified horizon evidence');}}>
      <label>Metric horizon<select value={horizon} onChange={e => setHorizon(e.target.value)}>{Object.keys(HOURS).map(h => <option key={h}>{h}</option>)}</select></label>
      <p>Window: {start} to {end}. {kind === 'exact_rolling' ? 'Values must cover exactly this interval.' : 'Counters must have been captured at this age; a late current total cannot stand in for it.'}</p>
      <label>Metric source<input required value={source} onChange={e => setSource(e.target.value)} placeholder="For example, Creator Studio export"/></label>
      <label>Metric evidence<input required value={evidence} onChange={e => setEvidence(e.target.value)} placeholder="Saved report or screenshot reference"/></label>
      <label>Measured at (local time)<input required type="datetime-local" value={measured} onChange={e => setMeasured(e.target.value)}/></label>
      {Object.entries(fields).map(([key, label]) => <label key={key}>{label}<input type="number" min="0" step={key.endsWith('_s') || key.endsWith('_pct') || key.endsWith('_ctr') ? 'any' : '1'}
        value={metrics[key] || ''} onChange={e => setMetrics({...metrics, [key]: e.target.value})}/></label>)}
      <label><input required type="checkbox"/>I verified the source, units and complete window shown above.</label>
      <button type="submit">Record verified manual metrics</button>
    </form>
  </details>;
}
