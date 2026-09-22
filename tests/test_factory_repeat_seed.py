"""A fresh run must bind current analysis even when scene bytes match."""
from test_factory_analysis_gate import env, _seed, _complete, _sections
from modules.factory.autorun.service import AutoRun
from modules.factory.analysis.deep import bound_gate
from modules.factory.domain.errors import ContractError
import pytest


def test_repeat_seed_refreshes_same_blueprint_analysis_binding(env, monkeypatch):
    seed, art = _seed(env)
    s = env['s']
    _complete(env, seed)
    payload = {'beats': [{'id':'b1','start_s':0,'end_s':3,'role':'hook',
                         'confidence':'uncertain','visual_event':'dog misses the ball'}],
               'transcript':[{'id':'t1','start_s':0,'end_s':3,'text':'watch this dog'}],
               'music':{'role':'bed'}}
    monkeypatch.setattr(s.autorun, '_beats', lambda _: (payload, None, None))
    first = AutoRun(id='repeat-first',seed_id=seed.id,stage='blueprint')
    assert s.autorun._stage_blueprint(first) == 'next'
    bp = s.analysis.get(first.state['blueprint_id'])
    original_hash = bp.content_hash
    assert bp.analysis['revision'] == 1
    _sections(s.ref_analysis, seed.id)
    s.ref_analysis.review(seed.id,'offline-fixture','accept')
    second = AutoRun(id='repeat-second',seed_id=seed.id,stage='blueprint')
    # A pre-patch run may already be paused at draft. Recovery preserves
    # paid script data and returns to guarded preparation, not analysis.
    paused = AutoRun(id='repeat-paused', seed_id=seed.id, stage='draft',
                     state={'blueprint_id':bp.id, 'scripts':{'saved':'paid copy'}})
    assert s.autorun._stage_draft(paused) == 'next'
    assert paused.stage == 'blueprint'
    assert paused.state['scripts'] == {'saved':'paid copy'}
    assert s.autorun._stage_blueprint(second) == 'next'
    current = s.analysis.get(second.state['blueprint_id'])
    assert current.analysis['revision'] == 2
    assert current.content_hash == original_hash
    assert bound_gate(s.db, seed.id, art.sha256, current.analysis).revision == 2
    # Incomplete evidence must still fail closed; this is not a stale-gate
    # bypass or a restoration of semantic scene review.
    _sections(s.ref_analysis, seed.id)
    third = AutoRun(id='repeat-incomplete',seed_id=seed.id,stage='blueprint')
    with pytest.raises(ContractError, match='analysis_incomplete'):
        s.autorun._stage_blueprint(third)
