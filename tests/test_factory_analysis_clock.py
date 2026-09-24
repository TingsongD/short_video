"""The factory analyzes immutable 30 fps copies and produces 30 fps output."""
import hashlib
import json
import subprocess
from types import SimpleNamespace

import pytest

from modules.factory.bootstrap import bootstrap
from modules.factory.domain.clocks import RationalRate
from modules.factory.domain.errors import ContractError
from modules.factory.media.analysis_clock import analysis_media, is_cfr30
from modules.factory.media.probe import probe
from modules.factory.testing.fixtures import _moving_mp4
from test_factory_application import FakeHypit


def seed_video(s, root, rate, *, audio=True, vfr=False):
    src = root / 'source.mp4'
    if vfr:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
            'testsrc2=size=160x90:rate=60:duration=3', '-vf',
            "select='not(mod(n,2))+eq(n,5)'", '-fps_mode', 'vfr', '-c:v', 'libx264', str(src)], check=True)
    else:
        _moving_mp4(src, 3, size='160x90', rate=rate, audio=audio)
    seed, _ = s.seeds.submit_url('https://youtu.be/abcdefghijk')
    art = s.artifacts.intake_file(src, provenance='seed_source', source_key='clock-test', requested_kind='video')
    s.seeds.attach_media(seed.id, art.id)
    return seed.id, art, src


@pytest.mark.parametrize('rate', [24, 25, '30000/1001', 30, 60])
def test_analysis_copy_is_cfr30_cached_and_preserves_original_and_audio(tmp_path, rate):
    s = bootstrap(tmp_path)
    try:
        seed_id, art, src = seed_video(s, tmp_path, rate)
        original_hash = hashlib.sha256(src.read_bytes()).hexdigest()
        media = analysis_media(s.artifacts, art.id)
        dest = s.artifacts.verified_path(media['analysis_artifact_id'])
        assert is_cfr30(dest)
        assert abs(probe(dest).duration_s - probe(src).duration_s) <= 1/30 + .01
        assert (media['analysis_artifact_id'] == art.id) == (rate == 30)
        assert s.seeds.get(seed_id).source_asset_id == art.id
        assert hashlib.sha256(src.read_bytes()).hexdigest() == original_hash == media['original_sha256']
        assert analysis_media(s.artifacts, art.id) == media
        # AAC is copied, including its timestamp compensation: decoded audio
        # must remain sample-for-sample identical at the original time origin.
        def pcm(path):
            return subprocess.run(['ffmpeg','-v','error','-i',str(path),'-vn','-f','s16le','-'],
                                  check=True,capture_output=True).stdout
        assert pcm(src) == pcm(dest)
    finally:
        s.db.close()


def test_variable_timestamps_are_normalized_even_when_claimed_rate_is_30(tmp_path):
    s = bootstrap(tmp_path)
    try:
        _, art, src = seed_video(s, tmp_path, 60, audio=False, vfr=True)
        info = probe(src)
        info.video.avg_frame_rate = info.video.r_frame_rate = 30
        assert not is_cfr30(src, info)
        media = analysis_media(s.artifacts, art.id)
        assert media['analysis_artifact_id'] != art.id
        assert is_cfr30(s.artifacts.verified_path(media['analysis_artifact_id']))
    finally:
        s.db.close()


def test_all_analysis_paths_bind_normalized_bytes_and_original_identity(tmp_path):
    s = bootstrap(tmp_path)
    try:
        seed_id, art, _ = seed_video(s, tmp_path, 24)
        s.ref_analysis.hypit = FakeHypit()
        a = s.ref_analysis.start(seed_id, 'fixture')
        assert s.ref_analysis.start(seed_id, 'fixture').revision == a.revision
        a = s.ref_analysis._stage_acquire(a)
        assert a.source_asset_id == art.id and a.source_sha256 == art.sha256
        assert a.acquisition['fps'] == '30/1'
        assert a.acquisition['analysis_artifact_id'] != art.id
        observations = {'beats':[{'id':'whole','role':'hook','start_s':0,'end_s':3,
            'visual_event':'moving image','confidence':'reviewed'}],
            'transcript':[{'id':'tail','start_s':2.8,'end_s':3,'text':'ending'}], 'music':{'role':'bed'}}
        bp = s.analysis.import_observations(seed_id, observations, 'fixture')
        assert bp.clock == RationalRate(30, 1)
        assert bp.beats[0].source.end == bp.target_frames == 90
        assert bp.provenance['artifact_sha256'] == art.sha256
        assert bp.provenance['analysis_artifact_id'] == a.acquisition['analysis_artifact_id']
        assert bp.provenance['source_clock'] == {'num':30,'den':1}
        # A quote uses the normalized bytes while retaining the selected input.
        s.effect_work.prepare = lambda kind, provider, model, requests: requests[0]
        request = s.analysis_work.prepare(seed_id, {})
        assert request['artifact_id'] == a.acquisition['analysis_artifact_id']
        assert request['analysis_source_artifact_id'] == art.id
        # Flashcut's helper must decode those same normalized bytes.
        from modules.factory.analysis.source_evidence import binding_from_db
        from modules.factory.autorun.service import AutoRun
        from modules.factory.store.uow import utcnow
        run = AutoRun(schema_version='autorun.v1', id='clock-run', created_at=utcnow(), seed_id=seed_id)
        with s.db.uow() as u:
            u.records.put(run)
        a.transcript = {'status':'not_applicable'}
        s.ref_analysis._save(a)
        binding = binding_from_db(s.db, run.id)
        assert binding['source_artifact_id'] == request['artifact_id']
        assert binding['original_source_sha256'] == art.sha256
    finally:
        s.db.close()


def test_new_factory_output_rejects_a_legacy_non30_blueprint(tmp_path):
    s = bootstrap(tmp_path)
    try:
        bp = SimpleNamespace(status='accepted', clock=RationalRate(24,1))
        with pytest.raises(ContractError, match='output_clock_requires_30fps'):
            s.experiments.create('exp','seed',bp,None,[],[])
    finally:
        s.db.close()


def test_flashcut_helper_decodes_30fps_copy_of_24fps_seed(tmp_path):
    from modules.factory.analysis.evidence_policy import new_flashcut_policy
    from modules.factory.autorun.service import AutoRun
    from modules.factory.services.worker import ApplicationWorker
    from modules.factory.store.uow import utcnow
    s = bootstrap(tmp_path)
    try:
        src = tmp_path/'native24.mp4'
        _moving_mp4(src, .5, size='72x128', rate=24, audio=False)
        art = s.artifacts.intake_file(src, 'seed_source', 'native24')
        seed, _ = s.seeds.submit_url('https://youtu.be/abcdefghijk')
        s.seeds.attach_media(seed.id, art.id)
        s.ref_analysis.hypit = FakeHypit()
        a = s.ref_analysis.start(seed.id, 'fixture')
        a = s.ref_analysis._stage_acquire(a)
        a.transcript = {'status':'not_applicable'}
        s.ref_analysis._save(a)
        with s.db.uow() as u:
            u.records.put(AutoRun(schema_version='autorun.v1', id='normalized-helper', created_at=utcnow(), seed_id=seed.id))
        work = s.source_work.prepare('normalized-helper', new_flashcut_policy())
        result = ApplicationWorker(s).tick()
        assert result['status'] == 'complete', result
        record = s.source_evidence.get(work['evidence_id'])
        assert record['binding']['source_sha256'] != art.sha256
        assert record['binding']['original_source_sha256'] == art.sha256
        assert s.source_evidence.manifest(work['evidence_id'])['totals']['visual'] == 15
    finally:
        s.db.close()


def test_old_native_analysis_gets_new_revision_without_rewriting_history(tmp_path):
    s = bootstrap(tmp_path)
    try:
        seed_id, art, _ = seed_video(s, tmp_path, 24)
        s.ref_analysis.hypit = FakeHypit()
        a = s.ref_analysis.start(seed_id, 'fixture')
        a.acquisition = {'artifact_id':art.id,'sha256':art.sha256,'fps':'24/1','duration_s':3}
        a = s.ref_analysis._save(a)
        new = s.ref_analysis.start(seed_id, 'fixture')
        assert new.revision == a.revision + 1
        assert new.acquisition['analysis_artifact_id'] != art.id
        assert s.ref_analysis.get(seed_id, revision=a.revision).acquisition['fps'] == '24/1'
        assert s.ref_analysis.start(seed_id, 'fixture').revision == new.revision
    finally:
        s.db.close()
