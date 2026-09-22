"""Freeze concrete cumulative analysis bounds before paid authorization."""
from copy import deepcopy
from fractions import Fraction
import json

from ..domain.errors import ContractError
from ..domain.records import content_hash
from .flashcut_vertex import MODEL, ROUTE_LIMITS


def load_evidence(store,evidence_id):
    record=store.get(evidence_id)
    manifest=store.manifest(evidence_id)
    result={}
    for stage in ('clock','fusion','media'):
        chunks=[c for c in manifest['chunks'] if c['stage']==stage]
        if len(chunks)!=1:
            raise ContractError('analysis_evidence_unavailable',stage)
        result[stage]=store.blobs.read(chunks[0]['blob'])
    return record,result


def build_analysis_plan(store,evidence_id,adapter,transcript):
    record,evidence=load_evidence(store,evidence_id)
    clock,fusion,media=(evidence[k] for k in ('clock','fusion','media'))
    binding={'source_sha256':record['binding']['source_sha256'],'transcript_sha256':record['binding']['transcript_sha256'],
             'evidence_sha256':record['manifest']['sha256']}
    candidates=[{k:c[k] for k in ('id','kind','source_time','mandatory','support')} for c in fusion['candidates']]
    context={'source_duration':clock['duration'],'source_clock':{k:clock[k] for k in ('version','origin','video','audio')},
             'transcript':transcript,'candidates':candidates,
             'coverage':{'decoded_frames':clock['decoded_frames'],'encoded_frames':clock['decoded_frames']}}
    base={'task':'analyze_flashcut','model':MODEL,'prompt_version':'flashcut_understanding.v1',
          'binding':binding,'context':context,'limits':deepcopy(adapter.limits)}
    overview={**base,'scope':'whole','media':[{'id':'source','kind':'video',
        'artifact_id':record['binding']['source_artifact_id'],'sha256':binding['source_sha256'],
        'source_start':'0','source_end':clock['duration']}]}
    requests=[overview]
    windows=[{'id':f'window:{i}','kind':'video',**{k:w[k] for k in ('artifact_id','sha256','source_start','source_end')}}
             for i,w in enumerate(media['windows'])]
    images=[{'id':f"frame:{i['frame_index']}",'kind':'image',**{k:i[k] for k in ('artifact_id','sha256','source_time')}}
            for i in media['images']]
    # Greedy deterministic packing attempts validation against actual bytes.
    # Any item that cannot fit alone is a technical pause, never an omission.
    group=[]
    def target(items):
        chosen=set()
        for item in items:
            point=Fraction(item['source_time'])
            containing=[w for w in windows if Fraction(w['source_start'])<=point<Fraction(w['source_end'])]
            if not containing:raise ContractError('analysis_evidence_unavailable','image_context_window')
            nearest=min(containing,key=lambda w:(abs((Fraction(w['source_start'])+Fraction(w['source_end']))/2-point),w['id']))
            chosen.add(nearest['id'])
        relevant=[w for w in windows if w['id'] in chosen]
        return {**base,'scope':'window','media':relevant+items}
    for image in images:
        proposed=target(group+[image])
        try:
            adapter.prepared(proposed)
        except ContractError as error:
            if error.code!='flashcut_request_limit' or not group:
                raise
            requests.append(target(group))
            group=[image]
            adapter.prepared(target(group))
        else:
            group.append(image)
    if group:
        requests.append(target(group))
    # Windows without selected images are mandatory audio context too.
    used={m['id'] for req in requests[1:] for m in req['media'] if m['kind']=='video'}
    for window in windows:
        if window['id'] not in used:
            requests.append({**base,'scope':'window','media':[window]})
    if len(requests)+2>adapter.limits['requests']:
        raise ContractError('flashcut_request_limit','cumulative_requests', 'Mandatory source evidence exceeds the qualified envelope.')
    usages=[adapter.prepared(request)[1] for request in requests]
    quotes=[adapter.price(request) for request in requests]
    # Two single-request clarification rounds are reserved at full route bounds.
    limits=adapter.limits
    p=adapter.pricing
    import math
    clarification_cost=math.ceil((limits['input_tokens']*p['input_usd_micros_per_million']+
                                  limits['output_tokens']*p['output_usd_micros_per_million'])/1000000)
    envelope={'version':'analysis_envelope.v1','initial_requests':len(requests),'max_requests':len(requests)+2,
              'max_clarification_rounds':2,
              'max_images':sum(u['images'] for u in usages)+2*limits['images'],
              'max_windows':sum(u['windows'] for u in usages)+2*limits['windows'],
              'max_media_seconds':str(sum((Fraction(u['media_seconds']) for u in usages),Fraction(0))+2*limits['media_seconds']),
              'max_payload_bytes':sum(u['payload_bytes'] for u in usages)+2*limits['payload_bytes'],
              'max_input_tokens':sum(u['input_tokens_bound'] for u in usages)+2*limits['input_tokens'],
              'max_output_tokens':sum(u['output_tokens_bound'] for u in usages)+2*limits['output_tokens'],
              'reserve_usd_micros':sum(q['reserve_amount'] for q in quotes)+2*clarification_cost}
    plan={'version':'flashcut_analysis_plan.v1','binding':binding,'requests':requests,
          'usage_bounds':usages,'quotes':quotes,'envelope':envelope}
    plan['identity']=content_hash(plan)
    return plan


def jev_summaries(store,evidence_id):
    record,data=load_evidence(store,evidence_id)
    candidates=data['fusion']['candidates']
    # Chunk separately at the caller if there are more candidates. No omission.
    return {'task':'prioritize_evidence','model':'jev-1.13.0','rubric':'optional_evidence.v1',
            'binding':{'source_sha256':record['binding']['source_sha256'],
                       'transcript_sha256':record['binding']['transcript_sha256'],
                       'evidence_sha256':record['manifest']['sha256']},
            'candidates':[{'id':c['id'],'mandatory':c['mandatory'],
                'summary':f"Measured {c['kind']} at source {c['source_time']} seconds. Support: {', '.join(c['support'])}. Semantic interpretation unavailable."}
                for c in candidates]}


def build_clarification_request(plan,pending):
    """Group questions covered by the same media; never discard a question."""
    candidates={c['id']:c for c in plan['requests'][0]['context']['candidates']}
    def contains(request,wanted):
        point=candidates.get(wanted,{}).get('source_time')
        return any(m['id']==wanted or (point is not None and m['kind']=='video'
            and Fraction(m['source_start'])<=Fraction(point)<Fraction(m['source_end'])) for m in request['media'])
    choices=[r for r in plan['requests'] if contains(r,pending[0])]
    if not choices:raise ContractError('analysis_evidence_unavailable','clarification_media')
    original=min(choices,key=lambda r:(-sum(contains(r,p) for p in pending),
        sum((Fraction(m['source_end'])-Fraction(m['source_start']) for m in r['media'] if m['kind']=='video'),Fraction(0))))
    request=deepcopy(original)
    request.update(scope='clarification',response_contract='flashcut_structured.v1')
    request['context']['clarify_ids']=[p for p in pending if contains(request,p)]
    request['context']['clarification_instruction']='Resolve all named missing evidence from actual supplied media. Return grounded observations for each, or explicitly retain its ID in essential_missing. Never invent observations.'
    return request
