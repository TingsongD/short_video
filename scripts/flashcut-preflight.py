"""Unpaid local evidence/analysis quote. Never opens the application database.

Run with the explicitly installed helper Python. Input hashes must come from
verified source records. Output is an isolated quote workspace, not a live run
or reusable provider authorization. No credential access or network transport.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
for setting in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):
    os.environ[setting]='4'
os.environ['HF_HUB_OFFLINE']='1'


def verified(path,expected):
    with path.open('rb') as file:
        if hashlib.file_digest(file,'sha256').hexdigest()!=expected:
            raise ValueError('Input hash mismatch: '+path.name)


def no_transport(*args,**kwargs):
    raise RuntimeError('A quote must never submit a provider request.')


def preflight(args):
    from modules.factory.analysis.dense_source import analyze_source
    from modules.factory.analysis.evidence_policy import new_flashcut_policy
    from modules.factory.analysis.frame_encoder import PEEncoder
    from modules.factory.analysis.helper_readiness import verify_installation
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    from modules.factory.analysis.flashcut_vertex import FlashcutAnalyzer
    from modules.factory.analysis.flashcut_requests import build_analysis_plan,jev_summaries,load_evidence
    from modules.factory.analysis.jev import JevDecisions
    from modules.factory.artifacts.registry import ArtifactStore
    from modules.factory.store import Database
    from modules.factory.domain.records import content_hash
    verified(args.source,args.source_sha256)
    verified(args.transcript,args.transcript_sha256)
    verify_installation(ROOT)
    transcript=json.loads(args.transcript.read_text())
    pricing=json.loads(args.pricing.read_text())
    if args.destination.exists():
        if not args.resume or (args.destination/'quote.json').exists():
            raise ValueError('Refusing to overwrite a completed or unrequested preflight workspace.')
    else:
        if args.resume:
            raise ValueError('No preflight workspace exists to resume.')
        args.destination.mkdir(mode=0o700,parents=True)
    db=Database(args.destination/'preflight.db')
    try:
        artifacts=ArtifactStore(args.destination/'artifacts',db)
        artifact=artifacts.intake_file(args.source,'seed_source','flashcut-preflight')
        store=SourceEvidenceService(db,args.destination/'source_evidence')
        policy=new_flashcut_policy()
        binding={'seed_id':'unpaid-preflight','seed_revision':1,'source_artifact_id':artifact.id,
            'source_sha256':artifact.sha256,'analysis_revision':1,
            'transcript_sha256':args.transcript_sha256,'edit_token':content_hash(['preflight',binding_seed(args)])}
        if args.resume:
            rows=db.conn.execute("SELECT body FROM records WHERE kind='sourceevidence'").fetchall()
            if len(rows)!=1:
                raise ValueError('Preflight workspace must contain exactly one source-evidence binding.')
            record=json.loads(rows[0][0])
            if (record['run_id']!='unpaid-preflight' or record['binding']!=binding
                    or record['policy']!=policy):
                raise ValueError('Preflight source or policy binding changed; do not resume.')
        else:
            record=store.create('unpaid-preflight',binding,policy)
        encoder=PEEncoder(ROOT/'vendor/flashcut-perception-models',ROOT/'vendor/flashcut-helper/models/PE-Core-S16-384.pt')
        started=time.monotonic()
        analyze_source(store,record['id'],args.source,encoder,binding=binding)
        adapter=FlashcutAnalyzer(args.destination/'provider-state',artifacts,no_transport,
            'not-authenticated','quote-only',pricing['gemini'],transport=no_transport)
        plan=build_analysis_plan(store,record['id'],adapter,transcript.get('passages',[]))
        summary=jev_summaries(store,record['id'])
        jev=JevDecisions(args.destination/'jev-state',transport=no_transport,pricing=pricing['jev'])
        requests=[{**summary,'candidates':summary['candidates'][i:i+32]}
            for i in range(0,len(summary['candidates']),32)
            if any(not c['mandatory'] for c in summary['candidates'][i:i+32])]
        if len(requests)>20:raise ValueError('Jev candidate chunks exceed the saved route limit.')
        quotes=[jev.price(r) for r in requests]
        record,evidence=load_evidence(store,record['id'])
        # A separate final-word editorial request is not available before TTS.
        # Reserve its strict text/output maximum; never pretend it is concrete.
        import math
        p=pricing['gemini'];limits=adapter.limits
        editorial=math.ceil((limits['context_bytes']*p['input_usd_micros_per_million']+
            limits['output_tokens']*p['output_usd_micros_per_million'])/1000000)
        report={'version':'flashcut_preflight.v1','source_sha256':artifact.sha256,
            'transcript_sha256':args.transcript_sha256,'policy':policy,'pricing':pricing,
            'elapsed_seconds':round(time.monotonic()-started,3),
            'decoded_frames':evidence['clock']['decoded_frames'],
            'encoded_frames':store.manifest(record['id'])['totals']['visual'],
            'source_seconds':evidence['clock']['duration'],
            'selected_images':len(evidence['media']['images']),'selected_windows':len(evidence['media']['windows']),
            'analysis':plan['envelope'],'jev_requests':len(requests),
            'jev_reserve_usd_micros':sum(q['reserve_amount'] for q in quotes),
            'editorial_max_usd_micros':editorial,
            'analysis_plan_identity':plan['identity'],
            'analysis_and_editorial_reserve_usd_micros':plan['envelope']['reserve_usd_micros']+editorial+sum(q['reserve_amount'] for q in quotes),
            'excludes':['Existing script model, replacement TTS/repairs, music, footage/overlay repairs, final visual QC.',
                'No production budget authority, no provider qualification, no live run created.'],
            'network_requests':0}
        (args.destination/'analysis-plan.json').write_text(json.dumps(plan,sort_keys=True,indent=2)+'\n')
        (args.destination/'quote.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ('policy','pricing')},indent=2))
    finally:db.close()


def binding_seed(args):
    return [args.source_sha256,args.transcript_sha256]


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('source','transcript','pricing','destination'):
        parser.add_argument('--'+name,required=True,type=Path)
    for name in ('source-sha256','transcript-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--resume',action='store_true')
    preflight(parser.parse_args())
