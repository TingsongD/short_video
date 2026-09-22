import hashlib
import subprocess
import pytest
np = pytest.importorskip('numpy', reason='VALIDATION GAP: run isolated helper tests')


def test_dense_analysis_resumes_without_reencoding_completed_frames(tmp_path):
    from modules.factory.analysis.dense_source import analyze_source
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    from modules.factory.analysis.evidence_policy import new_flashcut_policy,legacy_flashcut_policy
    from modules.factory.store import Database
    clip = tmp_path/'fixture.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=72x128:r=30:d=1',
                    '-an', '-c:v', 'libx264', '-y', str(clip)], check=True)
    binding = dict(seed_id='seed-test', seed_revision=1, source_artifact_id='art-test',
                   source_sha256=hashlib.sha256(clip.read_bytes()).hexdigest(),
                   analysis_revision=1, transcript_sha256='b'*64, edit_token='c'*64)
    class Encoder:
        count = 0
        def encode(self, images):
            self.count += len(images)
            result = np.zeros((len(images), 512), dtype=np.float32)
            result[:, 0] = 1
            return result
    db = Database(tmp_path/'test.db')
    try:
        service = SourceEvidenceService(db, tmp_path/'source_evidence')
        record = service.create('run-test', binding, new_flashcut_policy())
        encoder = Encoder()
        result = analyze_source(service, record['id'], clip, encoder, binding=binding)
        assert result['status'] == 'complete' and encoder.count == 30
        resumed = SourceEvidenceService(db, tmp_path/'source_evidence')
        result2 = analyze_source(resumed, record['id'], clip, encoder, binding=binding)
        assert result2['manifest'] == result['manifest'] and encoder.count == 30
        assert resumed.manifest(record['id'])['totals']['visual'] == 30
        from modules.factory.analysis.flashcut_vertex import FlashcutAnalyzer
        from modules.factory.analysis.flashcut_requests import build_analysis_plan
        from modules.factory.artifacts.registry import ArtifactStore
        # The source identity must resolve through the normal media registry.
        artifacts=ArtifactStore(tmp_path/'artifacts',db)
        original=artifacts.intake_file(clip,'seed_source','original')
        assert original.sha256==binding['source_sha256']
        # This unit's synthetic binding predates registration. Use a fresh bound
        # evidence record to exercise the actual quoted production identity.
        current={**binding,'source_artifact_id':original.id}
        new=service.create('quoted-run',current,new_flashcut_policy())
        analyzed=analyze_source(service,new['id'],clip,encoder,binding=current)
        class Auth:
            def bearer(self):pytest.fail('Quotation must not request credentials')
        route=FlashcutAnalyzer(tmp_path/'route',artifacts,Auth(),'test','test',
               {'input_usd_micros_per_million':750000,'output_usd_micros_per_million':3750000,
                'valid_until':'2099-01-01T00:00:00Z','evidence':'fixture'},
               transport=lambda *a,**k: pytest.fail('Quotation must not submit'))
        plan=build_analysis_plan(service,new['id'],route,[])
        assert plan['envelope']['initial_requests']==2
        assert plan['envelope']['max_requests']==4
        assert plan['envelope']['reserve_usd_micros']>sum(q['reserve_amount'] for q in plan['quotes'])
        overview=plan['requests'][0]['media'][0]
        assert overview['source_sha256']==original.sha256
        assert overview['sha256']!=original.sha256
        assert plan['version']=='flashcut_analysis_plan.v2'
        assert plan['identity'] and analyzed['status']=='complete'
        legacy=service.create('legacy-quoted-run',current,legacy_flashcut_policy())
        analyze_source(service,legacy['id'],clip,encoder,binding=current)
        legacy_plan=build_analysis_plan(service,legacy['id'],route,[])
        assert legacy_plan['version']=='flashcut_analysis_plan.v1'
        assert 'candidate_index' not in legacy_plan
        assert legacy_plan['requests'][0]['media'][0]['sha256']==original.sha256
        assert all('mime_type' not in item for request in legacy_plan['requests']
                   for item in request['media'])
    finally:
        db.close()


def test_interrupted_second_chunk_reuses_first_256_positions(tmp_path):
    from modules.factory.analysis.dense_source import analyze_source
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    from modules.factory.analysis.evidence_policy import new_flashcut_policy
    from modules.factory.store import Database
    from modules.factory.domain.errors import ContractError
    clip = tmp_path/'fixture.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=72x128:r=30:d=10',
                    '-an','-c:v','libx264',str(clip)], check=True)
    binding = dict(seed_id='seed-test', seed_revision=1, source_artifact_id='art-test',
                   source_sha256=hashlib.sha256(clip.read_bytes()).hexdigest(),
                   analysis_revision=1, transcript_sha256='b'*64, edit_token='c'*64)
    class Encoder:
        count, fail = 0, True
        def encode(self, images):
            if self.fail and self.count == 256:
                raise ContractError('decode_failed', 'synthetic_interruption')
            self.count += len(images)
            vectors = np.zeros((len(images),512), dtype=np.float32)
            vectors[:,0] = 1
            return vectors
    db = Database(tmp_path/'db')
    try:
        service = SourceEvidenceService(db,tmp_path/'evidence')
        record = service.create('run',binding,new_flashcut_policy())
        encoder = Encoder()
        with pytest.raises(ContractError,match='decode_failed'):
            analyze_source(service,record['id'],clip,encoder,binding=binding)
        assert service.get(record['id'])['status'] != 'complete'
        encoder.fail = False
        result = analyze_source(service,record['id'],clip,encoder,binding=binding)
        assert result['status'] == 'complete' and encoder.count == 300
        assert [c['attempts'] for c in service.chunks(record['id'],'visual')] == [1,2]
    finally:
        db.close()
