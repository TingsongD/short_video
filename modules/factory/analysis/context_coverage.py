"""Resolve window-local coverage requests from already validated source evidence.

No provider calls or verdict rewriting. Semantic ambiguities and in-window
questions remain unresolved; only absent-media context can use this policy.
"""
from fractions import Fraction
from .flashcut_vertex import _covered_by_windows
from ..domain.errors import ContractError
from ..domain.records import content_hash
from ..execution.effects import wire_hash

POLICY='context_coverage.v1'


def resolve_context_coverage(requests,outputs,*,local_evidence=None):
    if not requests or len(requests)!=len(outputs):raise ContractError('analysis_media_mismatch','coverage_inputs')
    binding=requests[0]['binding'];duration=Fraction(requests[0]['context']['source_duration'])
    if any(q['binding']!=binding or out.get('binding')!=binding for q,out in zip(requests,outputs)):
        raise ContractError('analysis_media_mismatch','coverage_binding')
    if local_evidence and local_evidence['binding']!=binding:
        raise ContractError('analysis_media_mismatch','local_coverage_binding')
    local={o['candidate_id']:o for o in (local_evidence or {}).get('observations',[])}
    supporting=[]
    for index,(request,output) in enumerate(zip(requests,outputs)):
        source=next((m for m in request['media'] if m['id']=='source'),{})
        if (request['scope']!='whole' or output.get('scope')!='whole' or not output.get('analysis')
                or output['essential_missing'] or source.get('kind')!='video'
                or source.get('sha256')!=binding['source_sha256']
                or Fraction(source.get('source_start','-1'))!=0 or Fraction(source.get('source_end','-1'))!=duration):continue
        for obs in output['observations']:
            if (obs['confidence']=='observed' and obs['time_basis']=='source' and 'source' in obs['evidence_ids']
                    and obs['kind'] in ('action','cast','setup','reveal','reaction','callback','transition')):
                supporting.append((index,obs))
    coverage=[{'source_start':str(o['start_s']),'source_end':str(o['end_s'])} for _,o in supporting]
    pending=[];resolved=[]
    for index,(request,output) in enumerate(zip(requests,outputs)):
        windows=[m for m in request['media'] if m['kind']=='video']
        candidates={c['id']:c for c in request['context'].get('candidates',[])}
        for flag in output['essential_missing']:
            ranges=[];candidate=candidates.get(flag,{})
            if request['scope']=='window' and flag in local and candidate.get('kind')=='visual_change_candidate':
                resolved.append({'response_index':index,'flag':flag,'local_evidence_hash':content_hash(local_evidence),
                                 'supporting_observation_ids':[flag],'evidence_ids':local[flag]['evidence_ids']})
                continue
            if request['scope']=='window':
                if (flag.startswith('coverage:') and candidate.get('kind')=='context' and candidate.get('mandatory') is True
                        and candidate.get('support') and set(candidate['support'])<= {'opening','ending','baseline_coverage'}):
                    position=Fraction(candidate['source_time'])
                    # Do not reinterpret a question about media it actually saw.
                    if not any(Fraction(w['source_start'])<=position<Fraction(w['source_end']) for w in windows):
                        ranges=[(max(Fraction(0),position-Fraction(1,2)),min(duration,position+Fraction(1,2)))]
                elif flag=='source' and output.get('coverage_gap_recovery',{}).get('version')=='coverage_gap_recovery.v1':
                    ranges=[(Fraction(r['start_s']),Fraction(r['end_s']))
                            for r in output['coverage_gap_recovery']['claimed_ranges']]
                    if any(_covered_by_windows(start,end,windows) for start,end in ranges):ranges=[]
            if not ranges or any(not 0<=start<end<=duration or not _covered_by_windows(start,end,coverage) for start,end in ranges):
                pending.append({'response_index':index,'flag':flag});continue
            support=[{'response_index':i,'observation_id':o['id'],'request_hash':wire_hash(requests[i]),
                      'response_hash':content_hash(outputs[i])} for i,o in supporting
                     if any(Fraction(str(o['start_s']))<end and Fraction(str(o['end_s']))>start for start,end in ranges)]
            resolved.append({'response_index':index,'flag':flag,'ranges':[{'start_s':str(s),'end_s':str(e)} for s,e in ranges],
                             'supporting_observation_ids':[p['observation_id'] for p in support],'support':support})
    return {'version':POLICY,'binding':binding,'request_hashes':[wire_hash(q) for q in requests],
            'response_hashes':[content_hash(o) for o in outputs],'resolutions':resolved,'pending':pending}
