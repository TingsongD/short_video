"""Pre-caption visual evidence and bounded, independently quoted clip repairs."""
import json

from .policies import run_policies
from ..domain.records import content_hash
from .repair_effects import check


def inspect(service, run, plan, picture, download, index, artifact):
    s = service.s
    reference_binding = picture['request'].get('reference_clip_bindings')
    if reference_binding:
        pinned = reference_binding.get('clip_reviews', [])
        if index < len(pinned) and pinned[index]['artifact_id'] == artifact['id'] and pinned[index]['sha256'] == artifact['sha256']:
            review = s.commands.get(pinned[index]['job_id'])['command']['result']['result'].get('review') or {}
            if review.get('verdict') == 'pass' and review.get('overlay') in ('none', 'incidental'):
                return None
        return ('pause', 'reference_clip_binding_changed', 'This character-conditioned clip no longer matches its pre-anchor overlay check.',
                'Revalidate the exact clip and its dependent character anchors. No text-only replacement was submitted.')
    token = content_hash([plan['plan_hash'], picture['node_key'], index, artifact['sha256']])[:24]
    tag = 'overlay_qc_' + token
    cached = run.state.setdefault('overlay_reviews', {}).get(token)
    if not cached:
        adapter = s.providers.get('audiovisual_analysis')
        model = getattr(adapter, 'model', '')
        jobs = run.state.get(tag + '_jobs')
        if not jobs:
            return service._run_effect(run, 'analysis', 'audiovisual_analysis', model,
                [{'task': 'review_clip', 'model': model, 'artifact_id': artifact['id'],
                  'artifact_sha256': artifact['sha256'], 'expected': {'prompt': picture['request'].get('prompt', '')}}],
                tag, plan['experiment_id'], plan['experiment_revision'])
        outcome = check(service, run, jobs, 'overlay_review_failed')
        if outcome != 'next':
            return outcome
        cached = s.commands.get(jobs[0])['command']['result']['result'].get('review') or {}
        run.state['overlay_reviews'][token] = cached
        service._put(run)
    verdict, classification = cached.get('verdict'), cached.get('overlay')
    if verdict == 'pass' and classification in ('none', 'incidental'):
        return None
    if verdict != 'fail' or classification != 'unwanted' or not cached.get('notes'):
        return ('pause', 'overlay_qc_uncertain', f'{picture["consumers"]} clip {index + 1}: text may be environmental or an overlay; visual QC could not confirm.',
                'Inspect the raw clip and resolve the ambiguous visual evidence. No automatic regeneration was submitted.')
    identity = content_hash([picture['consumers'], picture['takes'], index])[:24]
    attempts = run.state.setdefault('overlay_repair_attempts', {})
    intents = run.state.setdefault('overlay_repair_intents', {})
    intent = intents.get(token)
    maximum = run_policies(run.params)['overlay_repairs']
    if intent is None:
        count = attempts.get(identity, 0)
        if count >= maximum:
            return ('pause', 'overlay_repair_exhausted', f'{picture["consumers"]} clip {index + 1}: unwanted overlays remain after {count}/{maximum} repairs.',
                    'Replace or revise this clip, then Resume. Shared or seed footage will not be substituted.')
        intent = {'tag': f'overlay_repair_{identity}_{count + 1}', 'ordinal': count + 1}
        attempts[identity] = count + 1
        run.state.setdefault('overlay_repair_labels', {})[identity] = (
            ', '.join(f"{take['variant']}:{take['slot']}" for take in picture['takes']) + f' clip {index + 1}')
        intents[token] = intent
        service._put(run)
    repair_tag = intent['tag']
    jobs = run.state.get(repair_tag + '_jobs')
    if not jobs:
        request = dict(picture['request'], model=picture['model'], duration_s=picture['allocations'][index]['duration_s'])
        request['prompt'] = request.get('prompt', '') + f'\nOverlay repair {intent["ordinal"]}: Generate clean footage with NO superimposed lettering, captions, subtitles, logos, watermarks or decorative text. Preserve the same characters, wardrobe, action and camera direction.'
        return service._run_effect(run, 'generation', picture['provider'], picture['model'], [request], repair_tag,
                                   plan['experiment_id'], plan['experiment_revision'])
    outcome = check(service, run, jobs, 'overlay_regeneration_failed')
    if outcome != 'next':
        return outcome
    result = s.commands.get(jobs[0])['command']['result']
    replacement = result.get('artifact_id')
    s.artifacts.verified_path(replacement)
    new = s.db.uow().artifacts.get(replacement)
    if new['sha256'] == artifact['sha256']:
        return ('pause', 'overlay_repair_no_change', 'The replacement has identical bytes to the rejected clip.',
                'Inspect the provider receipt before any further generation.')
    artifacts = list(download['artifact_ids'])
    artifacts[index] = replacement
    # Only this completed allocation changes. The original generation attempt,
    # reservation and artifact remain intact; the separate repair has its own
    # quote/authority/receipt. Render content identity includes selected hashes.
    with s.db.uow() as u:
        s.production._set(plan['id'], download['node_key'], artifact_ids=artifacts)
        u.events.append('plan:' + plan['id'], 'overlay_clip_replaced', {
            'download': download['node_key'], 'index': index, 'old_artifact': artifact['id'],
            'new_artifact': replacement, 'effect_job': jobs[0], 'visual_evidence': token})
    return 'wait'
