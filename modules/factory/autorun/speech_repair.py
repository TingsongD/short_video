"""Measured, budgeted repairs. Intent and counters survive worker restarts."""
import math

from .policies import run_policies
from .repair_effects import check


def repair(service, run, fits):
    maximum = run_policies(run.params)['speech_repairs']
    s = service.s
    eid = run.state['experiment_id']
    pending = run.state.get('speech_repair_pending')
    if not pending:
        failed = []
        for fkey, jid in fits.items():
            job = s.db.uow().jobs.get(jid)
            if not job or job['status'] not in ('failed', 'blocked'):
                continue
            if 'copy_revision_required' not in str(job['blocked_reason']):
                return None
            failed.append((fkey, jid))
        if not failed:
            return None
        # A first: common unchanged narration follows A without buying or
        # rewriting it separately. The changed B/C/D copy stays independent.
        fkey, jid = sorted(failed)[0]
        key, segment, _ = fkey.split(':', 2)
        identity = key + ':' + segment
        counts = run.state.setdefault('speech_repair_attempts', {})
        used = counts.get(identity, 0)
        if used >= maximum:
            return ('pause', 'speech_repair_exhausted', f'{identity}: {used}/{maximum} automatic repairs used; narration still does not fit.',
                    'Edit this segment’s complete copy or beat duration, then Resume. Timing limits are unchanged.')
        cmd = s.commands.get(jid)['command']['input']
        speech = s.audio_work.speech.get(cmd['speech_id'])
        measured = speech.get('raw_duration_s') or speech.get('duration_s')
        if not measured or measured <= 0:
            return ('pause', 'speech_measurement_missing', f'{identity}: measured narration duration is unavailable.',
                    'Restore or remeasure the existing audio before resuming; it will not be regenerated blindly.')
        variant = s.experiments._variant(eid, key)
        seg = next(item for item in variant.segments if item['id'] == segment)
        exp = s._current(eid)
        fps = exp.output_clock['num'] / exp.output_clock['den']
        duration = (seg['target']['end_frame'] - seg['target']['start_frame']) / fps
        text = seg['copy']
        pending = {'identity': identity, 'key': key, 'segment': segment,
                   'tag': f'speech_repair_{key}_{segment}_{used + 1}',
                   'revision': exp.revision,
                   'input': {'text': text, 'variant': key, 'hypothesis': variant.hypothesis,
                             'source_copy': (run.state.get('scripts_base', {}).get('A') or {}).get(segment, ''),
                             'measured_duration_s': measured, 'beat_duration_s': duration,
                             'max_words': max(1, min(len(text.split()) - 1, math.floor(len(text.split()) * duration / measured * .9)))}}
        # Reserve the attempt before any paid request. Crash recovery reuses
        # this exact intent; refusing budget does not mint another attempt.
        counts[identity] = used + 1
        run.state['speech_repair_pending'] = pending
        service._put(run)
    if s._current(eid).revision != pending['revision']:
        return ('pause', 'speech_repair_stale', 'The draft changed during narration repair.',
                'Reconcile the existing repair before starting another; the attempt counter is preserved.')
    tag = pending['tag']
    jobs = run.state.get(tag + '_jobs')
    if not jobs:
        adapter = s.providers.get('audiovisual_analysis')
        model = getattr(adapter, 'model', '')
        return service._run_effect(run, 'analysis', 'audiovisual_analysis', model,
                                   [{'task': 'shorten_speech', 'model': model, 'repair_input': pending['input']}],
                                   tag, eid, pending['revision'])
    result = check(service, run, jobs, 'speech_repair_failed')
    if result != 'next':
        return result
    payload = s.commands.get(jobs[0])['command']['result']['result'].get('rewrite') or {}
    if not payload.get('usable'):
        reason = payload.get('reason') or 'No reliable rewrite returned.'
        used = run.state.get('speech_repair_attempts', {}).get(
            pending['identity'], 0)
        run.state.setdefault('speech_repair_rejections', []).append({
            'identity': pending['identity'], 'attempt': used,
            'reason': reason,
        })
        # The completed response was unusable, not unknown. Preserve its
        # receipt and mint a distinct, bounded next attempt identity. An
        # uncertain request never reaches this branch and remains paused in
        # repair_effects.check without being replayed.
        run.state.pop('speech_repair_pending', None)
        service._put(run)
        if used >= maximum:
            return ('pause', 'speech_repair_exhausted',
                    f"{pending['identity']}: {used}/{maximum} automatic repairs used; {reason}",
                    'Edit this segment’s complete copy or beat duration, then Resume. Timing limits are unchanged.')
        return 'next'
    with s.db.uow():
        result = service._patch_speech(run, [(pending['key'], pending['segment'], payload['text'])],
                                       run.state['scripts_base'], measured_repair=True)
        if result == 'next':
            run.state.pop('speech_repair_pending', None)
            service._put(run)
    return result
