"""Unpaid, reproducible PE/audio benchmark on a labeled synthetic fixture.

Run ONLY with the explicitly installed helper Python. No provider construction,
credential loading, network access, model downloads or production DB access.
The destination must not exist; results and the local media fixture are retained.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def benchmark(destination):
    from modules.factory.analysis.dense_source import analyze_source
    from modules.factory.analysis.evidence_policy import new_flashcut_policy
    from modules.factory.analysis.frame_encoder import PEEncoder
    from modules.factory.analysis.helper_readiness import verify_installation
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    from modules.factory.artifacts.registry import ArtifactStore
    from modules.factory.store import Database
    if destination.exists():raise SystemExit('Refusing to overwrite an existing benchmark directory.')
    verify_installation(ROOT)
    destination.mkdir(mode=0o700,parents=True)
    source=destination/'labeled.mp4'
    video="color=red:s=180x320:r=30:d=9,drawbox=color=white:t=fill:enable='between(n,96,97)',drawbox=color=blue:t=fill:enable='between(n,150,209)'"
    audio='aevalsrc=0.25*sin(2*PI*90*t)|-0.25*sin(2*PI*90*t):s=48000:d=9'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',video,'-f','lavfi','-i',audio,
        '-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
    db=Database(destination/'benchmark.db')
    try:
        artifacts=ArtifactStore(destination/'artifacts',db)
        artifact=artifacts.intake_file(source,'seed_source','offline-benchmark')
        store=SourceEvidenceService(db,destination/'source_evidence')
        policy=new_flashcut_policy()
        binding={'seed_id':'benchmark','seed_revision':1,'source_artifact_id':artifact.id,
                 'source_sha256':artifact.sha256,'analysis_revision':1,
                 'transcript_sha256':hashlib.sha256(b'[]').hexdigest(),'edit_token':'b'*64}
        record=store.create('benchmark',binding,policy)
        started=time.perf_counter()
        encoder=PEEncoder(ROOT/'vendor/flashcut-perception-models',ROOT/'vendor/flashcut-helper/models/PE-Core-S16-384.pt')
        result=analyze_source(store,record['id'],source,encoder,binding=binding)
        cold=time.perf_counter()-started
        started=time.perf_counter()
        resumed=analyze_source(store,record['id'],source,encoder,binding=binding)
        warm=time.perf_counter()-started
        manifest=store.manifest(record['id'])
        chunks={c['stage']:store.blobs.read(c['blob']) for c in manifest['chunks'] if c['stage'] in ('clock','fusion')}
        selected=set(chunks['fusion']['selected_frame_indices'])
        audio_chunks=[store.blobs.read(c['blob']) for c in manifest['chunks'] if c['stage']=='audio']
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
        report={'version':'flashcut_benchmark.v1','fixture_sha256':artifact.sha256,
            'policy':policy,'python':sys.version,'cold_seconds':cold,'warm_seconds':warm,
            'peak_rss_bytes':peak,'disk_bytes':sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()),
            'decoded_frames':chunks['clock']['decoded_frames'],'encoded_frames':manifest['totals']['visual'],
            'cache_identity_preserved':result['manifest']==resumed['manifest'],
            'labels':{'two_frame_flash':sorted({96,97}&selected),'quiet_opening_retained':0 in selected,
                'ending_retained':269 in selected,'callback_boundary_retained':210 in selected,
                'antiphase_audio_measured':any(c.get('status')=='measured' for c in audio_chunks)},
            'limitations':['Synthetic fixture only; not a semantic accuracy or virality benchmark.',
                'Warm run reuses immutable completed chunks, not a cold model load.',
                'No hosted Jev/Gemini calls; advisory cost/quality benefit remains unmeasured.']}
        (destination/'report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ('policy','python')},indent=2))
        if (report['encoded_frames']!=270 or report['decoded_frames']!=270
                or report['labels']['two_frame_flash']!=[96,97]
                or not all(v for k,v in report['labels'].items() if k!='two_frame_flash')
                or not report['cache_identity_preserved']):raise SystemExit('Labeled fixture benchmark failed.')
    finally:db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination',type=Path)
    benchmark(parser.parse_args().destination.resolve())
