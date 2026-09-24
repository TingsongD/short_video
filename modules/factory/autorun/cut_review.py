"""Bound local citation review; never mutates provider jobs or their money."""
import hashlib
import json
from copy import deepcopy
from ..analysis.cut_review import apply_cut_review
from ..domain.errors import ContractError
from ..execution.effects import wire_hash


def supplement_request(request, review, siblings, verify):
    """Local review view only; the paid request and its hash stay unchanged."""
    digest = review.get('supplemental_request_hash')
    digests = review.get('supplemental_request_hashes')
    if digest is None and digests is None:
        return request, None
    if digests is None:
        digests = [digest]
    elif digest is not None:
        raise ContractError('cut_review_unproven', 'supplement_hashes')
    if (not isinstance(digests,list) or not 1 <= len(digests) <= 20
            or any(not isinstance(d,str) for d in digests) or len(set(digests)) != len(digests)):
        raise ContractError('cut_review_unproven', 'supplement_hashes')
    donor = {}
    for wanted in digests:
        matches = [s for s in siblings if wire_hash(s) == wanted]
        if len(matches) != 1 or matches[0].get('binding') != request.get('binding'):
            raise ContractError('cut_review_unproven', 'supplement_binding')
        sibling = matches[0]
        verify(sibling)
        for item in sibling['media']:
            if item['id'] in donor and donor[item['id']] != item:
                raise ContractError('cut_review_unproven', 'supplement_conflict')
            donor[item['id']] = item
    media = {m['id']: m for m in request['media']}
    if any(media[k] != donor[k] for k in media.keys() & donor.keys()):
        raise ContractError('cut_review_unproven', 'supplement_conflict')
    try:
        needed = {c[k] for c in review['corrections'] for k in ('before_frame_id', 'after_frame_id')} - media.keys()
        if not 1 <= len(needed) <= 64 or any(donor[k]['kind'] != 'image' for k in needed):
            raise ValueError()
        extra = [deepcopy(donor[k]) for k in sorted(needed)]
    except (KeyError, TypeError, ValueError):
        raise ContractError('cut_review_unproven', 'supplement_frames') from None
    effective = {**request, 'media': [*request['media'], *extra]}
    identity = {'request_hash': digest} if digest is not None else {'request_hashes': digests}
    return effective, {**identity, 'binding': request['binding'], 'media': extra}


def frozen_review_requests(store, plan):
    requests = list(plan['requests'][:-1])
    if plan.get('prior_plan'):
        prior = store.blobs.read(plan['prior_plan'])
        if any(prior.get(k) != plan.get(k) for k in ('run_id', 'binding', 'original_plan_identity')):
            raise ContractError('cut_review_unproven', 'prior_plan_binding')
        requests.extend(prior['requests'])
    return list({wire_hash(r): r for r in requests}.values())


class CutReview:
    def __init__(self, auto):
        self.auto, self.s = auto, auto.s

    def inspect(self, run, request, job_id, review):
        adapter = self.s.providers['audiovisual_analysis_flashcut']
        job = self.s.db.uow().jobs.get(job_id)
        attempts = list(self.s.db.conn.execute(
            "SELECT * FROM attempts WHERE job_id=? AND status NOT IN ('failed','cancelled','succeeded')", (job_id,)))
        if (not job or job['status'] != 'failed' or len(attempts) != 1
                or attempts[0]['status'] != 'unknown' or attempts[0]['remote_id']
                or attempts[0]['id'] != review.get('attempt_id')
                or attempts[0]['request_hash'] != wire_hash(request)):
            raise ContractError('cut_review_unproven', 'attempt')
        proof = adapter.inspect_saved_response(request, attempts[0]['id'], validate=False)
        if proof['finish_reason'] != 'STOP' or proof['response_sha256'] != review.get('provider_response_sha256'):
            raise ContractError('cut_review_unproven', 'response')
        folder = adapter.root / ('sync-' + hashlib.sha256(attempts[0]['id'].encode()).hexdigest()[:32])
        saved = (folder / 'provider-response.json').read_bytes()
        if hashlib.sha256(saved).hexdigest() != proof['saved_response_sha256']:
            raise ContractError('cut_review_unproven', 'changed_response')
        # Re-establish immutable request/evidence binding and actual media bytes.
        adapter.prepared(request)
        value = adapter._response_content(json.loads(saved)['response'])
        plan = self.s.source_evidence.blobs.read(run.state['flashcut_format_recovery'])
        effective, supplement = supplement_request(request, review,
            frozen_review_requests(self.s.source_evidence, plan), adapter.prepared)
        result = apply_cut_review(value, effective, review, preserve_gaps=True)
        if supplement:
            result['cut_citation_review']['supplemental_evidence'] = supplement
        return {'version': 'reviewed_cut_response.v1', 'run_id': run.id, 'job_id': job_id,
                'proof': proof, 'review': review,
                'result': {**result, 'scope': request['scope'], 'binding': request['binding']}}

    def enable(self, run, review):
        if (run.status != 'paused' or run.stage != 'video_analysis'
                or not run.state.get('flashcut_format_recovery') or not isinstance(review, dict)):
            raise ContractError('cut_review_unavailable', 'run')
        plan = self.s.source_evidence.blobs.read(run.state['flashcut_format_recovery'])
        matches = [(request, ids[0]) for index, request in enumerate(plan['requests'][:-1])
                   if len(ids := run.state.get(f'flashcut_format_{index}_jobs', [])) == 1
                   and ids[0] == review.get('job_id')]
        if len(matches) != 1:
            raise ContractError('cut_review_unavailable', 'job')
        request, job_id = matches[0]
        evidence = self.inspect(run, request, job_id, review)
        ref = self.s.source_evidence.blobs.put(evidence)
        previous = run.state.get('flashcut_cut_reviews', {}).get(job_id)
        if previous and previous != ref:
            raise ContractError('cut_review_changed', 'review')
        if not previous:
            run.state.setdefault('flashcut_cut_reviews', {})[job_id] = ref
            self.s.db.uow().events.append('autorun:' + run.id, 'cut_citation_review_recorded', {
                'job_id': job_id, 'evidence': ref, 'reviewer_type': review['reviewer_type'],
                'new_requests': 0, 'accounting': 'unknown_retained'})

    def collect(self, run, request, job_id):
        ref = run.state.get('flashcut_cut_reviews', {}).get(job_id)
        if not ref:
            return None
        saved = self.s.source_evidence.blobs.read(ref)
        if self.inspect(run, request, job_id, saved['review']) != saved:
            raise ContractError('cut_review_changed', 'evidence')
        from .flashcut_recovery import FlashcutResponseRecovery
        FlashcutResponseRecovery(self.auto).release_completed_capacity(job_id, request)
        return {**saved['result'], 'cut_review_evidence': ref}
