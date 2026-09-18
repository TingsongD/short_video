"""Review probes — INVERTED after the 2026-09-18 fix wave.

These originally asserted defect behavior for Q01–Q13 (a passing probe
confirmed the bug). They now assert the repaired behavior and serve as
regression coverage for the findings they reproduced.

Run: PYTHONPATH=.:tests .venv/bin/python -m pytest -q -s <this file>
Only temporary databases and fake providers are used.
"""
import json

import pytest

from modules.factory.store import Database
from modules.factory.learning.service import LearningService
from modules.factory.publishing.service import PublishingService
from modules.factory.seeds.registry import SeedRegistry
from modules.factory.domain.records import Artifact, Publication
from modules.factory.domain.errors import ContractError
from modules.factory.testing.fakes import FakeAnalytics
from test_factory_analytics import _publication, _svc
from test_factory_seed_selection import _experiment, _policy, _lanes
from test_factory_rounds import _setup, _rounds, _selection, _freeze


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / 'review.db')


def selection_setup(db, **policy):
    _experiment(db)
    service = LearningService(db)
    _policy(service, seed_policy={'mode': 'primary_platform',
        'primary_platform': 'tiktok', 'provisional_horizon': '48h'}, **policy)
    return service


def mutate_snapshots(db, change):
    for row in db.conn.execute("SELECT * FROM records WHERE kind='metricsnapshot'").fetchall():
        body = json.loads(row['body'])
        change(body)
        db.conn.execute('UPDATE records SET body=? WHERE kind=? AND id=?',
                        (json.dumps(body), 'metricsnapshot', row['id']))


def test_q01_underexposed_challenger_cannot_win(db):
    """Q01: exposure floor now joins guardrails in §9.3 eligibility —
    a below-minimum challenger is disqualified, not crowned."""
    service = selection_setup(db, primary_metric='avg_view_pct',
                              exposure_metric='views', min_exposure=100)
    _lanes(db, 'exp-1', ['tiktok'], {k: {'tiktok': v}
           for k, v in zip('ABCD', [1000, 1, 1000, 1000])})
    def change(body):
        body['metrics']['avg_view_pct'] = 100 if '-b-' in body['id'] else 50
        body['availability']['avg_view_pct'] = 'ok'
    mutate_snapshots(db, change)
    result = service.select_seed('exp-1', 1)
    assert result['winner_variant'] != 'B'
    assert 'B' in result['basis'].get('disqualified', {})


def test_q02_stale_late_evidence_is_ineligible(db):
    """Q02: a lifetime-at-age observation recorded 'late' measured a
    different age than the horizon declares — excluded, not crowned."""
    service = selection_setup(db)
    _lanes(db, 'exp-1', ['tiktok'], {k: {'tiktok': v}
           for k, v in zip('ABCD', [100, 200, 90, 80])})
    def change(body):
        body['actual_coverage'] = {'late': True, 'observed_age_hours': 672}
        body['requested_period']['upstream_freshness'] = '2020-01-01T00:00:00+00:00'
    mutate_snapshots(db, change)
    result = service.select_seed('exp-1', 1)
    assert result['outcome'] == 'waiting'
    assert not result['winner_variant']


def test_q04_complete_requested_days_are_complete(db):
    """Q04: expected days equal the requested window — the midnight-
    aligned publication day is inside it (Sep 10–16), not an extra."""
    _publication(db)
    days = [f'2026-09-{d:02}' for d in range(10, 17)]
    fake = FakeAnalytics(analytics_rows=[[d, 18, 60, 2, 80, 4, 1, 1, 100] for d in days],
                         reach_rows=[[d, 200, 5] for d in days])
    service, _ = _svc(db, fake)
    snap = service.collect('pub-1', '7d_complete', now='2026-09-19T10:00:00+00:00')
    assert snap.requested_period['start'] == '2026-09-10'
    assert snap.actual_coverage['expected_days'] == days
    assert snap.completeness == 'complete'


def test_q05_optional_reach_does_not_block_views(db):
    """Q05: optional thumbnail reach absence leaves required coverage
    complete — a views-based comparison can proceed (§8.2)."""
    _publication(db)
    service, _ = _svc(db, FakeAnalytics(reach_rows=[]))
    snap = service.collect('pub-1', '48h', now='2026-09-12T10:00:00+00:00')
    assert snap.metrics['views'] == 2400
    assert snap.completeness == 'complete'


def test_q08_refused_cancel_reports_failed(db):
    """Q08: a provider-refused cancel is reported honestly — never
    'cancelled' while the remote job still fires."""
    class Publisher:
        def cancel_schedule(self, job_id):
            return {'success': False, 'error': 'still scheduled'}
        def status(self, *args, **kwargs):
            return {'status': 'scheduled'}
    with db.uow() as u:
        u.records.put(Publication(schema_version='publication.v1', id='p',
            created_at='2026-09-17T12:00:00+00:00', variant_plan_id='v',
            final_sha256='ab' * 32, platform='tiktok', account_id='a',
            job_id='j', request_id='r', status='scheduled'))
    service = PublishingService(db, publisher=Publisher())
    assert service.cancel_remote('p')['outcome'] == 'cancel_failed'


def test_q09_proposed_seed_carries_champion_media(db):
    """Q09: the child seed binds the winner's accepted local master —
    readiness resolves, no lineage placeholder."""
    _setup(db)
    art = Artifact(schema_version='artifact.v1', id='art-win',
                   created_at='2026-09-17T12:00:00+00:00',
                   sha256='ab' * 32, kind='video', byte_count=10)
    with db.uow() as u:
        u.artifacts.register(art)
        u.records.put(Publication(
            schema_version='publication.v1', id='pub-b',
            created_at='2026-09-17T12:00:00+00:00',
            variant_plan_id='vp-exp-1-b', final_sha256='ab' * 32,
            platform='youtube', account_id='a', status='public',
            artifact_id='art-win', published_at='2026-09-17T10:00:00+00:00',
            experiment_revision=1))
    rounds = _rounds(db)
    _freeze(rounds)
    result = rounds.propose_next('exp-1', 1, _selection(db))
    assert result['winner_media']['status'] == 'media_ready'
    assert result['winner_media']['artifact_id'] == 'art-win'
    readiness = SeedRegistry(db).readiness(result['seed']['id'])
    assert readiness['analysis_ready'] is True


def test_q13_default_round_limit_replay_is_idempotent(db):
    """Q13: the idempotent-child check precedes the round limit — a
    replay under the default max_rounds=1 returns the same child."""
    _setup(db)
    rounds = _rounds(db)
    _freeze(rounds, max_rounds=1)
    selection = _selection(db)
    first = rounds.propose_next('exp-1', 1, selection)
    again = rounds.propose_next('exp-1', 1, selection)
    assert again['idempotent'] is True
    assert again['lineage']['id'] == first['lineage']['id']
