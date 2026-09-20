"""Read-only, offline incident probes; FAIL means the defect is still present.

Run: .venv/bin/python docs/factory-reports/reproduce-last-run-issues.py
No services are instantiated, no requests are submitted, no DB writes occur.
"""
import copy
import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from modules.factory.analysis.analyzer import parse_analysis
from modules.factory.autorun.review import build_sections
from modules.factory.autorun.scripts import beat_copy
from modules.factory.autorun.service import AutoRunService
from modules.factory.domain.errors import ContractError

DB = sqlite3.connect(f"file:{ROOT / 'data/factory/factory.db'}?mode=ro", uri=True)
RUN_ID = 'auto-cd98a5cf5308471b'
EID = 'exp-' + RUN_ID


def record(kind, rid):
    row = DB.execute('SELECT body FROM records WHERE kind=? AND id=? '
                     'ORDER BY revision DESC LIMIT 1', (kind, rid)).fetchone()
    return json.loads(row[0])


def final(key):
    row = DB.execute('SELECT value FROM meta WHERE key=?',
                     ('final:' + EID + ':' + key.lower(),)).fetchone()
    return json.loads(row[0])


def timing_coverage():
    payload = copy.deepcopy(record('autorun', RUN_ID)['state']['analysis'])
    analysis = record('referenceanalysis', 'ra-seed-youtube-caca10adc130afb5')
    duration = analysis['acquisition']['duration_s']
    try:
        parsed = parse_analysis(payload)
        sections = build_sections(parsed, duration, round(duration * 30))
    except ContractError:
        return
    span = max(b['end_s'] for b in parsed['beats'])
    assert span >= duration - .5, (
        f'{span}s of beats accepted for {duration}s source; '
        f'last timeline beat expanded to {sections["timeline"][-1]["end_s"]}s')


def single_passage_owner():
    passage = [{'start_s': .5, 'end_s': 1.5, 'text': 'One spoken line.'}]
    beats = [{'start_s': 0, 'end_s': 1}, {'start_s': 1, 'end_s': 2}]
    copies = [beat_copy(b, passage) for b in beats]
    assert sum(bool(c) for c in copies) == 1, f'one passage assigned {len([c for c in copies if c])} times: {copies}'


def copy_variations():
    variants = {k: record('variantplan', EID + ':' + k.lower()) for k in 'ABCD'}
    source = {s['id']: s.get('copy') for s in variants['A']['segments']}
    missing = [k for k in 'BCD' if not any(
        s.get('copy') != source[s['id']] for s in variants[k]['segments'])]
    mixes = {final(k)['mix']['artifact_id'] for k in 'ABCD'}
    assert not missing, f'no copy changes in {missing}; distinct audio mixes={len(mixes)}'


def consistent_resolution():
    dimensions = {}
    for key in 'ABCD':
        art = json.loads(DB.execute('SELECT body FROM artifacts WHERE id=?',
                                   (final(key)['artifact_id'],)).fetchone()[0])
        dimensions[key] = (art['native_width'], art['native_height'])
    assert len(set(dimensions.values())) == 1, str(dimensions)


def failed_check_blocks_completion():
    run = SimpleNamespace(params={'visual_reviews': False}, state={}, notes=[])
    failed_review = record('review', 'regions-build-3582a794433bc5c95ff929e7')
    assert failed_review['verdict'] == 'fail', 'incident evidence changed'
    calls = []
    fake = SimpleNamespace(_finish=lambda r: calls.append('finished'),
                           s=SimpleNamespace(quality=SimpleNamespace(
                               _get=lambda cid: failed_review)))
    result = AutoRunService._stage_final_qc(fake, run)
    assert 'finished' not in calls, f'final QC returns {result!r} and finishes without consulting failed check'


failed = 0
for check in (timing_coverage, single_passage_owner, copy_variations,
              consistent_resolution, failed_check_blocks_completion):
    try:
        check()
        print('PASS', check.__name__)
    except AssertionError as exc:
        failed += 1
        print('FAIL', check.__name__ + ':', exc)
DB.close()
sys.exit(1 if failed else 0)
