"""Bridge final speech and variant-owned generated clips to native authoring."""
from fractions import Fraction
import json

from ..analysis.editorial_events import EditorialService
from ..audio.phrase_captions import phrase_cues
from ..domain.clocks import RationalRate
from ..domain.errors import ContractError


def final_passages(services,experiment,variant):
    clock=RationalRate(**experiment.output_clock)
    passages=[];captions=[]
    for index,segment in enumerate(variant.segments):
        if not segment.get('copy'):
            continue
        speech=segment.get('speech') or {}
        if not speech.get('speech_id'):
            raise ContractError('semantic_alignment_required',segment['id'],'Final fitted narration must retain its alignment record.')
        final=services.audio_work.alignment.final_alignment(speech['speech_id'],services.audio_work.speech.get,clock,speech['speech_hash'])
        if any(final[k]!=speech.get(k) for k in ('artifact_id','alignment_hash')):
            raise ContractError('stale_alignment',segment['id'])
        if (final['in_frame'],final['out_frame'])!=(segment['target']['start_frame'],segment['target']['end_frame']):
            raise ContractError('semantic_passage_interval',segment['id'])
        services.artifacts.verified_path(final['artifact_id'])
        cues=phrase_cues([{**w,'word_refs':[i]} for i,w in enumerate(final['words'])],
                        final['text'],final['in_frame'],final['out_frame'])
        passage={**final,'id':f'p{index}','segment_id':segment['id'],'phrases':[c['word_refs'] for c in cues]}
        passages.append(passage)
        captions.extend({'id':f'phrase-{index}-{n}','placement':'heading',
                         **{k:c[k] for k in ('text','start_frame','end_frame')}} for n,c in enumerate(cues))
    return passages,captions


def planning_input(services,experiment):
    from ..domain.records import content_hash
    saved=experiment.packaging['flashcut_editorial']
    understanding=services.source_evidence.blobs.read(saved['understanding'])
    if understanding['binding']['evidence_sha256']!=saved['evidence_sha256']:
        raise ContractError('editorial_evidence_mismatch','understanding')
    bp=services.analysis.get(services._experiment_blueprint(experiment)['id'])
    source={b.id:float(Fraction(b.source.start,bp.clock.num)*bp.clock.den) if b.source else None for b in bp.beats}
    variants={}
    for key in 'ABCD':
        variant=services.experiments._variant(experiment.experiment_id,key)
        passages,_=final_passages(services,experiment,variant)
        variants[key]={'passages':passages,'hypothesis':getattr(variant,'hypothesis',''),
            'footage':[{'id':seg['id'],'in_frame':seg['target']['start_frame'],
                'out_frame':seg['target']['end_frame'],'source_start_s':source[seg['id']]} for seg in variant.segments]}
    inputs={'version':'editorial_input.v1','clock':experiment.output_clock,
        'total_frames':experiment.packaging['target_frames'],'variants':variants,
        'observations':understanding['observations'],
        'creative_context':experiment.packaging.get('creative_context',{})}
    binding={'experiment_id':experiment.experiment_id,'revision':experiment.revision,
        'speech':content_hash(variants),'understanding':saved['understanding']['sha256'],
        'policy':content_hash(experiment.packaging['flashcut_policy']),'input_sha256':content_hash(inputs)}
    return inputs,binding,understanding['binding']


def output_binding(services,experiment):
    from ..analysis.editorial_planning import PlanningStore
    from ..domain.records import content_hash
    from ..composition.native import frozen_package
    _,binding,_=planning_input(services,experiment)
    store=PlanningStore(services.db,services.source_evidence.blobs.root)
    intent=store.get(binding)
    if not intent:raise ContractError('editorial_intent_required','quote')
    _,package_hash=frozen_package()
    return {'editorial_manifest':intent['manifest'],'policy_hash':content_hash(experiment.packaging['flashcut_policy']),
            'author_package_hash':package_hash}


def prepare_editorial(services,experiment,variant,pictures,mix):
    passages,captions=final_passages(services,experiment,variant)
    clock=RationalRate(**experiment.output_clock)
    inventory=[]
    rate=Fraction(clock.num,clock.den)
    for picture in pictures:
        artifact=services.db.uow().artifacts.get(picture['artifact_id'])
        services.artifacts.verified_path(artifact['id'])
        probe=json.loads(artifact['probe']);video=next((s for s in probe['streams'] if s['codec_type']=='video'),{})
        if artifact['kind']!='video' or video.get('duration_s') is None:
            raise ContractError('editorial_video_range_unavailable',picture['id'],'A probed generated video range is required.')
        # Decimal ffprobe duration may round one frame down. Prefer the
        # rational CFR frame count; VFR ranges need separately decoded evidence.
        if video.get('vfr'):
            raise ContractError('editorial_video_range_unavailable',picture['id'],'Generated footage must have a qualified CFR clock.')
        if video.get('nb_frames') and video.get('avg_frame_rate'):
            frames=int(Fraction(video['nb_frames'])/Fraction(video['avg_frame_rate'])*rate)
        else:
            frames=int(Fraction(str(video['duration_s']))*rate)
        inventory.append({**picture,'variant_key':variant.variant_key,'available_frames':frames})
    saved=experiment.packaging.get('flashcut_editorial')
    if not isinstance(saved,dict):
        raise ContractError('editorial_intent_required','flashcut_editorial')
    if saved.get('understanding'):
        from ..analysis.editorial_planning import PlanningStore
        inputs,binding,_=planning_input(services,experiment)
        planner=PlanningStore(services.db,services.source_evidence.blobs.root)
        intent=planner.get(binding)
        if not intent:raise ContractError('editorial_intent_required','final_speech_binding')
        proposed=planner.load(intent)['plans'][variant.variant_key]['events']
        specs=[]
        for event in proposed:
            beat=next(f for f in inputs['variants'][variant.variant_key]['footage'] if f['id']==event['footage_id'])
            source=beat['in_frame']+event['source_in_frame']
            clip=next((p for p in inventory if p['in_frame']<=source<source+event['duration_frames']<=p['out_frame']),None)
            if not clip:
                raise ContractError('editorial_allocation_boundary',event['id'],'The requested cut crosses separately generated clips; preserve the plan and correct that edit.')
            specs.append({k:v for k,v in {**event,'footage_id':clip['id'],
                'source_in_frame':source-clip['in_frame']+round(Fraction(str(clip.get('source_in_s',0)))*rate)}.items()
                if k not in ('artifact_id','sha256','start_frame','end_frame','semantic_start','variant_key')})
    else:
        # Explicit plans are useful for offline fixture compilation. Production
        # drafts require an immutable understanding bundle at creation.
        specs=saved.get('events',{}).get(variant.variant_key)
        if specs is None:raise ContractError('editorial_intent_required','events')
    service=EditorialService(services.db,services.source_evidence.blobs.root)
    record=service.freeze(experiment.experiment_id,experiment.revision,variant.variant_key,experiment.output_clock,
        variant.target_frames,inventory,passages,specs,
        {'source_evidence':saved['evidence_sha256'],'policy':experiment.packaging['flashcut_policy'],
         'mix_sha256':mix['sha256']})
    resolved=service.load(record['id'])
    return record,resolved,captions
