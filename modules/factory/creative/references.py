"""Disabled-by-default first-clip anchors with exact, receipted dependencies.

Each effect is quoted only once its actual references exist. Re-entry observes
the existing job; it never substitutes text generation for missing anchors.
"""
import copy
import tempfile
from pathlib import Path

from ..domain.errors import ContractError
from ..domain.records import content_hash
from ..planning.asset_graph import expand_take


def role_dependencies(context, variant):
    """Topological order follows scene order; new roles are pinned afterward."""
    first, result = {}, []
    for scene in context['scenes']:
        known = {role: first[role] for role in scene['cast'] if role in first}
        new = [role for role in scene['cast'] if role not in first]
        result.append({'variant': variant, 'scene': scene['beat_id'], 'requires': known, 'establishes': new})
        for role in new:
            first[role] = scene['beat_id']
    return result


def conditioned_request(request, anchors, roles, variant):
    out = copy.deepcopy(request)
    refs, hashes, pins = [], {}, {}
    for role in roles:
        anchor = anchors[role]
        if anchor['variant'] != variant or anchor['role'] != role:
            raise ContractError('reference_variant_mismatch', 'role', role)
        aid = anchor['artifact_id']
        if aid not in refs:
            refs.append(aid)
        hashes[aid] = anchor['sha256']
        pins[role] = anchor['sha256']
    out.update(reference_artifact_ids=refs, reference_roles={a: 'image' for a in refs},
               reference_hashes=hashes, role_reference_hashes=pins, reference_policy='first_clip.v1')
    return out


def _pause(code, detail):
    return ('pause', code, detail, 'Reference-conditioned generation is stopped. Resolve the named evidence or route problem; no text-only fallback was submitted.')


def scene_allocations(duration, cap, known_roles, scene_roles):
    """First appearance may be text-only; later chunks use the image route."""
    offset, result = 0, []
    while offset < duration - 1e-6:
        mode = 'image_ref' if known_roles or (result and scene_roles) else 'text'
        selected = cap.get('mode_capabilities', {}).get(mode, cap)
        fit = expand_take(duration - offset, selected.get('durations_s', []))
        if fit['status'] != 'ok':
            raise ContractError('reference_duration_unavailable', mode)
        allocation = dict(fit['allocations'][0], offset_s=offset, input_mode=mode)
        result.append(allocation)
        offset += allocation['covers_s']
    for allocation in result:
        allocation['split'] = len(result) > 1
    return result


def prepare(service, run):
    s = service.s
    exp = s._current(run.experiment_id, run.state['experiment_revision'], True)
    context = exp.packaging.get('creative_context')
    if exp.packaging.get('run_policies', {}).get('variation') != 'full_video':
        return _pause('reference_requires_full_video', 'Character-conditioned variants are multi-variable full-video comparisons, not isolated controlled-region tests.')
    if not context or context.get('evidence_quality') == 'roles_unavailable':
        return _pause('reference_roles_unavailable', 'No reliable recurring-role evidence is available for this source.')
    allowed = exp.provider_policy.allowed_models.get('google_vertex', [])
    adapter = s.providers.get('google_vertex')
    if exp.provider_policy.choice != 'vertex' or not adapter or len(allowed) != 1:
        return _pause('reference_route_unavailable', 'First-clip references require the configured Google route.')
    model = allowed[0]
    cap = adapter.capabilities(model)
    if not cap.get('reference_enabled') or 'image_ref' not in cap.get('qualified_modes', []):
        return _pause('reference_route_unqualified', 'The image-reference route is disabled until separately authorized live qualification.')
    analyzer = s.providers.get('audiovisual_analysis')
    if not analyzer:
        return _pause('reference_validator_unavailable', 'Visual reference-frame validation is not configured.')
    fps = exp.output_clock['num'] / exp.output_clock['den']
    state = run.state.setdefault('reference_work', {})
    bindings = run.state.setdefault('reference_bindings', {})
    from ..autorun.repair_effects import check
    from ..autorun.policies import run_policies
    repair_limit = run_policies(run.params)['overlay_repairs']
    from ..media.frames import extract_frame
    for variant in 'ABCD':
        anchors = {}
        segments = s.experiments._variant(exp.experiment_id, variant).segments
        for segment in segments:
            request = segment['picture']['request']
            roles = request.get('cast_roles', [])
            new_roles = [role for role in roles if role not in anchors]
            known = [role for role in roles if role in anchors]
            duration = (segment['target']['end_frame'] - segment['target']['start_frame']) / fps
            allocation_key = content_hash([variant, segment['id'], request, duration, segment.get('picture', {}).get('handle_s', 0)])
            pinned_allocations = run.state.setdefault('reference_allocations', {})
            if allocation_key not in pinned_allocations:
                pinned_allocations[allocation_key] = scene_allocations(duration + segment.get('picture', {}).get('handle_s', 0), cap, known, roles)
                service._put(run)
            allocations = pinned_allocations[allocation_key]
            assets, hashes, requests, clip_reviews, effects = [], [], [], [], []
            for index, allocation in enumerate(allocations):
                req = conditioned_request(request, anchors, [r for r in roles if r in anchors], variant)
                req.update(model=model, duration_s=allocation['duration_s'], variant_identity=variant,
                           scene_chunk=index, scene_offset_s=allocation['offset_s'])
                identity = content_hash([exp.experiment_id, variant, segment['id'], req])
                repairs = run.state.setdefault('reference_overlay_repairs', {})
                ordinal = repairs.get(identity, 0)
                if ordinal:
                    req['prompt'] += f' Overlay repair {ordinal}: absolutely no superimposed lettering, subtitles, logos or watermarks.'
                    req['overlay_repair'] = ordinal
                tag = 'reference_clip_' + content_hash([identity, ordinal])[:24]
                jobs = run.state.get(tag + '_jobs')
                if not jobs:
                    return service._run_effect(run, 'generation', 'google_vertex', model, [req], tag, exp.experiment_id, exp.revision)
                result = check(service, run, jobs, 'reference_generation_failed')
                if result != 'next':
                    return result
                generated = s.commands.get(jobs[0])['command']['result']
                aid = generated.get('artifact_id')
                path = s.artifacts.verified_path(aid)
                artifact = s.db.uow().artifacts.get(aid)
                if artifact['kind'] != 'video':
                    return _pause('reference_clip_invalid', segment['id'])
                overlay_tag = 'reference_overlay_' + content_hash([identity, ordinal, artifact['sha256']])[:24]
                overlay_jobs = run.state.get(overlay_tag + '_jobs')
                if not overlay_jobs:
                    return service._run_effect(run, 'analysis', 'audiovisual_analysis', analyzer.model,
                        [{'task':'review_clip', 'model':analyzer.model, 'artifact_id':aid,
                          'artifact_sha256':artifact['sha256'], 'expected':{'policy':'visual.v2', 'prompt':req['prompt']}}],
                        overlay_tag, exp.experiment_id, exp.revision)
                checked = check(service, run, overlay_jobs, 'reference_overlay_failed')
                if checked != 'next':
                    return checked
                overlay = s.commands.get(overlay_jobs[0])['command']['result']['result'].get('review') or {}
                if overlay.get('verdict') == 'fail' and overlay.get('overlay') == 'unwanted':
                    if ordinal >= repair_limit:
                        return _pause('reference_overlay_exhausted', f'{variant}:{segment["id"]}: overlays remain after {repair_limit} authorized repairs.')
                    repairs[identity] = ordinal + 1
                    service._put(run)
                    return 'wait'
                if overlay.get('verdict') != 'pass' or overlay.get('overlay') not in ('none', 'incidental'):
                    return _pause('reference_overlay_uncertain', f'{variant}:{segment["id"]}: overlay evidence remains uncertain.')
                assets.append(aid)
                hashes.append(artifact['sha256'])
                requests.append(content_hash(req))
                attempt = s.executor._attempt(generated['attempt_id'])
                paid_request = s.executor._intent_body(attempt['id'])['request']
                expected_request = {**req, 'workflow_version':2, 'autorun_id':run.id, 'workflow_effect':tag}
                if paid_request != expected_request:
                    return _pause('reference_binding_stale', f'{variant}:{segment["id"]}: the original paid request no longer matches this scene and its references.')
                effects.append({'job_id': jobs[0], 'attempt_id': attempt['id'],
                                'request_hash': attempt['request_hash'], 'request': copy.deepcopy(paid_request)})
                clip_reviews.append({'job_id': overlay_jobs[0], 'artifact_id': aid, 'sha256': artifact['sha256']})
                if new_roles:
                    anchor_key = content_hash([identity, artifact['sha256'], new_roles])
                    entry = state.get(anchor_key)
                    if entry is None:
                        with tempfile.TemporaryDirectory(prefix='factory-anchor-') as folder:
                            frame = extract_frame(path, min(allocation['covers_s'] / 2, allocation['duration_s'] / 2), Path(folder) / 'frame.png')
                            image = s.artifacts.intake_file(frame, provenance='generated_frame', source_key='anchor:' + anchor_key,
                                source_detail='generated clip:' + artifact['sha256'], requested_kind='image')
                        entry = {'artifact_id': image.id, 'sha256': image.sha256, 'clip_sha256': artifact['sha256']}
                        state[anchor_key] = entry
                        service._put(run)
                    s.artifacts.verified_path(entry['artifact_id'])
                    review_tag = 'reference_check_' + anchor_key[:24]
                    review_jobs = run.state.get(review_tag + '_jobs')
                    if not review_jobs:
                        return service._run_effect(run, 'analysis', 'audiovisual_analysis', analyzer.model,
                            [{'task': 'review_anchor', 'model': analyzer.model, 'artifact_id': entry['artifact_id'],
                              'artifact_sha256': entry['sha256'], 'expected': {'role_ids': new_roles,
                                  'roles': [r for r in context['roles'] if r['id'] in new_roles], 'scene_id': segment['id']}}],
                            review_tag, exp.experiment_id, exp.revision)
                    result = check(service, run, review_jobs, 'reference_validation_failed')
                    if result != 'next':
                        return result
                    review = s.commands.get(review_jobs[0])['command']['result']['result'].get('review') or {}
                    if review.get('verdict') != 'pass' or set(review.get('roles') or []) != set(new_roles):
                        return _pause('reference_anchor_unreliable', f'{variant}:{segment["id"]}: no clear verified frame for {new_roles}.')
                    for role in new_roles:
                        anchors[role] = {**entry, 'variant': variant, 'role': role, 'review_job': review_jobs[0]}
                    new_roles = []
            bindings[variant + ':' + segment['id']] = {'request_hash': content_hash(request), 'artifact_ids': assets,
                'artifact_hashes': hashes, 'generation_requests': requests, 'anchors': copy.deepcopy(anchors),
                'allocations': copy.deepcopy(allocations), 'clip_reviews': clip_reviews, 'effects': effects,
                'adopted_into_revision': exp.revision}
            service._put(run)
    return None


def bound_request(s, exp, variant, segment, request, bindings):
    binding = bindings.get(variant + ':' + segment['id'])
    if not binding or binding.get('request_hash') != content_hash(request) or binding.get('adopted_into_revision') != exp.revision:
        raise ContractError('reference_binding_stale', 'segment', segment['id'])
    aids, hashes = binding.get('artifact_ids', []), binding.get('artifact_hashes', [])
    if not aids or len(aids) != len(hashes):
        raise ContractError('reference_binding_invalid', 'segment', segment['id'])
    effects = binding.get('effects', [])
    if len(effects) != len(aids):
        raise ContractError('reference_binding_invalid', 'effects')
    from ..execution.effects import wire_hash
    for aid, sha, effect in zip(aids, hashes, effects):
        s.artifacts.verified_path(aid)
        row = s.db.uow().artifacts.get(aid)
        if not row or row['sha256'] != sha or row['provenance'] != 'google_vertex':
            raise ContractError('reference_binding_invalid', 'artifact_id', aid)
        job = s.db.uow().jobs.get(effect.get('job_id'))
        command = s.commands.get(effect['job_id'])['command']
        result = command.get('result') or {}
        attempt = s.executor._attempt(effect['attempt_id'])
        intent = s.executor._intent_body(effect['attempt_id'])
        expected = effect['request']
        if (not job or job['status'] != 'succeeded' or job['experiment_id'] != exp.experiment_id
                or job['revision'] > exp.revision or result.get('artifact_id') != aid
                or result.get('attempt_id') != effect['attempt_id'] or attempt['job_id'] != job['id']
                or attempt['status'] != 'downloaded' or intent.get('provider') != 'google_vertex'
                or intent.get('request') != expected or wire_hash(expected) != effect['request_hash']
                or attempt['request_hash'] != effect['request_hash']
                or expected.get('variant_identity') != variant or expected.get('scene_id') != segment['id']):
            raise ContractError('reference_binding_invalid', 'effect', effect['attempt_id'])
    return {**request, 'artifact_ids': aids, 'reference_clip_bindings': copy.deepcopy(binding)}
