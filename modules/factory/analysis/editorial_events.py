"""Resolve editorial relationships only after replacement speech is final.

Story beats, speech passages, generated assets and short picture edits are
independent identities. Nothing here calls a provider, changes speech or uses
seed pixels. The supplied footage inventory belongs to exactly one variant.
"""
from copy import deepcopy
from dataclasses import dataclass, field
from fractions import Fraction
import json

from .source_evidence import EvidenceBlobs
from ..domain.errors import ContractError
from ..domain.records import Record, content_hash
from ..store.uow import utcnow


def resolve_edits(footage,passages,specs,clock,variant,total_frames):
    fps=Fraction(clock['num'],clock['den'])
    inventory={p['id']:p for p in footage}
    if not inventory or len(inventory)!=len(footage) or any(p.get('variant_key')!=variant for p in footage):
        raise ContractError('editorial_footage_binding','variant')
    cursor=0
    for picture in sorted(footage,key=lambda p:p['in_frame']):
        if picture['in_frame']!=cursor or picture['out_frame']<=cursor:
            raise ContractError('editorial_coverage_invalid','footage')
        cursor=picture['out_frame']
        if picture.get('transition_out','cut') not in ('cut','none',''):
            raise ContractError('editorial_transition_unqualified','footage','Flash-cut edits require explicit hard cuts.')
    if cursor!=total_frames:
        raise ContractError('editorial_coverage_invalid','total_frames')
    events=[];seen=set()
    for spec in specs:
        ident=spec.get('id')
        if not isinstance(ident,str) or not ident or ident in seen:
            raise ContractError('editorial_event_identity','event')
        seen.add(ident)
        anchor=spec['anchor'];moment=None
        if anchor['kind']=='speech':
            passage=next((p for p in passages if p['id']==anchor.get('passage_id')),None)
            index=anchor.get('word_index')
            if not passage or type(index) is not int or not 0<=index<len(passage['words']):
                raise ContractError('editorial_anchor_unavailable',ident,'Final narration no longer contains the required word.')
            word=passage['words'][index]
            if word['text']!=anchor.get('text') or anchor.get('edge') not in ('start','end'):
                raise ContractError('editorial_anchor_mismatch',ident,'Word index and exact spoken text must agree.')
            point=word['start_frame' if anchor['edge']=='start' else 'end_frame']
            offset=Fraction(anchor.get('offset_s','0'))
            intended=Fraction(point)/fps+offset
            first=round(intended*fps)
            if anchor['edge']=='start' and offset==0 and (index>0 or point==passage['in_frame']):
                moment=f'{passage["id"]}-word-{index}'
        elif anchor['kind'] in ('visual','music') and anchor.get('evidence_id'):
            intended=Fraction(anchor['target_time'])
            first=round(intended*fps)
        else:
            raise ContractError('editorial_anchor_unavailable',ident,'Wordless edits require explicit visual/music evidence.')
        duration=spec.get('duration_frames')
        if type(duration) is not int or duration<1 or not 0<=first<first+duration<=total_frames:
            raise ContractError('editorial_interval_conflict',ident)
        clip=inventory.get(spec.get('footage_id'));source=spec.get('source_in_frame')
        if not clip or type(source) is not int or source<0 or source+duration>clip['available_frames']:
            raise ContractError('editorial_source_range_invalid',ident,'No seed or shared-variant substitute is allowed.')
        event={**deepcopy(spec),'start_frame':first,'end_frame':first+duration,'artifact_id':clip['artifact_id'],
               'sha256':clip['sha256'],'variant_key':variant,
               'target_time_before_quantization':str(intended),
               'quantization_error_seconds':str(Fraction(first)/fps-intended)}
        if moment:event['semantic_start']=moment
        events.append(event)
    events.sort(key=lambda e:(e['start_frame'],e['id']))
    if any(a['end_frame']>b['start_frame'] for a,b in zip(events,events[1:])):
        raise ContractError('editorial_interval_conflict','events','Required placements overlap; do not move or drop events silently.')
    boundaries=sorted({0,total_frames,*[p[k] for p in footage for k in ('in_frame','out_frame')],
                      *[e[k] for e in events for k in ('start_frame','end_frame')]})
    pictures=[]
    for low,high in zip(boundaries,boundaries[1:]):
        event=next((e for e in events if e['start_frame']<=low<e['end_frame']),None)
        if event:
            original=inventory[event['footage_id']]
            source=event['source_in_frame']+low-event['start_frame']
        else:
            original=next(p for p in footage if p['in_frame']<=low< p['out_frame'])
            source=round(Fraction(str(original.get('source_in_s',0)))*fps)+low-original['in_frame']
        if source+high-low>original['available_frames']:
            raise ContractError('editorial_source_range_invalid',original['id'])
        # No environment-specific paths enter durable editorial identities.
        item={k:v for k,v in original.items() if k not in ('src','path','semantic_start','available_frames')}
        item.update(id='edit-'+content_hash([original['id'],low,high,event['id'] if event else 'base'])[:20],
                    in_frame=low,out_frame=high,source_in_s=float(Fraction(source)/fps),
                    source_out_s=float(Fraction(source+high-low)/fps),transition_out='cut',transition_frames=0)
        if event and low==event['start_frame'] and event.get('semantic_start'):
            item['semantic_start']=event['semantic_start']
        pictures.append(item)
    return {'version':'semantic_edits.v1','variant_key':variant,'passages':deepcopy(passages),
            'pictures':pictures,'events':events,'clock':clock,'total_frames':total_frames}


@dataclass
class EditorialPlan(Record):
    status:str='resolved'
    experiment_id:str=''
    experiment_revision:int=0
    variant_key:str=''
    binding:dict=field(default_factory=dict)
    manifest:dict=field(default_factory=dict)


class EditorialService:
    def __init__(self,db,root):
        self.db,self.blobs=db,EvidenceBlobs(root)

    def freeze(self,eid,revision,variant,clock,total,footage,passages,specs,binding):
        result=resolve_edits(footage,passages,specs,clock,variant,total)
        bound={**binding,'experiment_id':eid,'revision':revision,'variant_key':variant,
               'editorial_policy':'semantic_edits.v1','resolved_hash':content_hash(result)}
        ident='editorial-'+content_hash(bound)[:32]
        with self.db.uow() as u:
            existing=u.records.get('editorialplan',ident)
            if existing:
                record=json.loads(existing['body']);self.blobs.read(record['manifest'])
                return record
            manifest=self.blobs.put(result)
            record=EditorialPlan(schema_version='editorial_plan.v1',id=ident,created_at=utcnow(),
                experiment_id=eid,experiment_revision=revision,variant_key=variant,binding=bound,manifest=manifest)
            u.records.put(record)
        return record.to_dict()

    def load(self,ident):
        row=self.db.uow().records.get('editorialplan',ident)
        if not row:raise ContractError('editorial_unavailable','id')
        return self.blobs.read(json.loads(row['body'])['manifest'])
