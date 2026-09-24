"""Point cuts use cited frame boundaries, never an invented event duration."""
from copy import deepcopy
import pytest
from modules.factory.analysis.flashcut_vertex import validate_observations
from modules.factory.testing.fakes import ProviderError


def sample():
    request = {'scope': 'window', 'response_contract': 'flashcut_compact.v2',
               'context': {'source_duration': '8'}, 'media': [
        {'id': 'window:0', 'kind': 'video', 'source_start': '0', 'source_end': '4'},
        {'id': 'frame:63', 'kind': 'image', 'source_time': '21/10'},
        {'id': 'frame:64', 'kind': 'image', 'source_time': '32/15'}]}
    value = {'essential_missing': [], 'observations': [{
        'id': 'cut', 'kind': 'cut', 'start_s': 2.133, 'end_s': 2.133,
        'time_basis': 'source', 'description': 'Entrance to seafood counter.',
        'evidence_ids': ['window:0', 'frame:63', 'frame:64'], 'role_ids': [],
        'confidence': 'observed', 'text_role': 'none'}]}
    return request, value


def test_point_cut_retains_report_and_measured_adjacent_frame_interval():
    request, value = sample()
    before = deepcopy((request, value))
    item = validate_observations(value, request)['observations'][0]
    assert item['start_s'] == 2.1 and item['end_s'] == 64 / 30
    assert item['cut_frame_bracket'] == {
        'version': 'cut_frame_bracket.v1', 'reported_source_time': '2133/1000',
        'before_frame_id': 'frame:63', 'after_frame_id': 'frame:64',
        'before_source_time': '21/10', 'after_source_time': '32/15'}
    assert (request, value) == before


@pytest.mark.parametrize('bad', ['kind', 'uncited', 'nonadjacent', 'wrong_time',
                                'reverse_clock', 'outside_video', 'legacy', 'gap', 'relative'])
def test_point_cut_requires_bound_adjacent_frames_and_other_validation(bad):
    request, value = sample()
    item = value['observations'][0]
    if bad == 'kind': item['kind'] = 'action'
    if bad == 'uncited': item['evidence_ids'].remove('frame:63')
    if bad == 'nonadjacent':
        request['media'][1]['id'] = 'frame:62'
        item['evidence_ids'][1] = 'frame:62'
    if bad == 'wrong_time': item.update(start_s=2.12, end_s=2.12)
    if bad == 'reverse_clock': request['media'][1]['source_time'] = '3'
    if bad == 'outside_video': request['media'][0]['source_start'] = '2.12'
    if bad == 'legacy': request.pop('response_contract')
    # A gap intersecting the assigned video remains unresolved. A wholly
    # external interval is retained separately by compact window validation.
    if bad == 'gap': value['coverage_gaps'] = [{'start_s': 3.9, 'end_s': 8}]
    if bad == 'relative': item['time_basis'] = 'window:0'
    with pytest.raises(ProviderError, match='malformed_flashcut_analysis'):
        validate_observations(value, request)
