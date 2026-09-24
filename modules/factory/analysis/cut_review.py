"""Explicit visual-review corrections of frame citations, with original evidence."""
from copy import deepcopy
from ..domain.errors import ContractError
from .flashcut_vertex import validate_observations, validate_provisional_gaps


def apply_cut_review(value, request, review, *, preserve_gaps=False):
    try:
        if (request.get('scope') != 'window'
                or request.get('response_contract') != 'flashcut_compact.v2'
                or review['reviewer_type'] not in ('assistant', 'human')
                or not isinstance(review['reviewer'], str) or not review['reviewer'].strip()
                or not isinstance(review['corrections'], list) or not 1 <= len(review['corrections']) <= 32):
            raise ValueError()
        corrected = deepcopy(value)
        observations = {o['id']: o for o in corrected['observations']}
        media = {m['id']: m for m in request['media']}
        seen = set()
        for change in review['corrections']:
            identifier = change['observation_id']
            if identifier in seen:
                raise ValueError()
            seen.add(identifier)
            item = observations[identifier]
            if (item['kind'] != 'cut' or item['time_basis'] != 'source'
                    or item['start_s'] != item['end_s']):
                raise ValueError()
            for field in ('before_description', 'after_description'):
                if not isinstance(change[field], str) or not 1 <= len(change[field].strip()) <= 2000:
                    raise ValueError()
            pair = [change['before_frame_id'], change['after_frame_id']]
            if len(set(pair)) != 2 or any(media[i]['kind'] != 'image' for i in pair):
                raise ValueError()
            # Retain every cited video. The strict validator derives the exact
            # adjacent frame interval and still checks timing/coverage/types.
            item['evidence_ids'] = [i for i in item['evidence_ids'] if media[i]['kind'] != 'image'] + pair
        result = (validate_provisional_gaps(corrected, request)
                  if preserve_gaps and corrected.get('coverage_gaps')
                  else validate_observations(corrected, request))
        for change in review['corrections']:
            measured = next(o for o in result['observations'] if o['id'] == change['observation_id'])['cut_frame_bracket']
            if any(measured[key] != change[key] for key in ('before_frame_id', 'after_frame_id')):
                raise ValueError()
        result['cut_citation_review'] = {
            'version': 'cut_citation_review.v1', 'reviewer': review['reviewer'],
            'reviewer_type': review['reviewer_type'], 'corrections': deepcopy(review['corrections']),
            'original_observations': deepcopy(value['observations'])}
        return result
    except (KeyError, TypeError, ValueError):
        raise ContractError('cut_review_invalid', 'review') from None
