"""Collect approved synthesis into measured, reviewed experiment speech."""
import copy
import json
import uuid
from ..audio.speech import SpeechService
from ..audio.alignment import AlignmentService
from ..domain.clocks import RationalRate
from ..domain.errors import ContractError
from ..store.uow import utcnow


class AudioWork:
    def __init__(self, services):
        self.s=services
        self.speech=SpeechService(services.db,services.artifacts)
        self.alignment=AlignmentService(services.db,None)

    def queue_fit(self, eid, revision, body):
        exp=self.s._current(eid,revision,True)
        key=body.get('variant_key');segment=body.get('segment_id');source=body.get('job_id')
        if key not in ('A','B','C','D') or not segment or not source:raise ContractError('invalid_speech_binding','variant/segment/job')
        variant=self.s.experiments._variant(eid,key)
        seg=next((x for x in variant.segments if x['id']==segment),None)
        if not seg:raise ContractError('unknown_segment','segment_id')
        command=self.s.commands.get(source)
        if command['status']!='succeeded' or command['command']['kind']!='effect':raise ContractError('synthesis_unfinished','job_id')
        effect=self.s.effect_work.get(command['command']['input']['plan_id'])
        if effect['kind']!='tts' or effect['experiment_id']!=eid or effect['experiment_revision']>revision:
            raise ContractError('speech_scope_mismatch','job_id')
        operation=next(x for x in effect['operations'] if x['key']==command['command']['input']['operation'])
        req=operation['request']
        if req.get('text')!=self.speech.normalize(seg.get('copy','')):raise ContractError('speech_copy_mismatch','text')
        sid='speech-'+uuid.uuid4().hex
        voice={k:req.get(k) for k in ('voice_id','model','language','settings')}
        self.speech.plan_segment(sid,variant.id,req['text'],voice,seg['target'],utcnow())
        binding={'experiment_id':eid,'revision':revision,'variant_key':key,'segment_id':segment,'speech_id':sid,'job_id':source,'clock':exp.output_clock}
        with self.s.db.uow() as u:u.conn.execute('INSERT INTO meta VALUES(?,?)',('speech-binding:'+sid,json.dumps(binding)))
        return self.s.commands.enqueue('speech_fit',binding,experiment_id=eid,revision=revision,phase='render')

    def fit(self,body):
        self.s._current(body['experiment_id'],body['revision'],True)
        source=self.s.commands.get(body['job_id'])['command']['result'];aid=source['artifact_id']
        self.s.artifacts.verified_path(aid);art=self.s.db.uow().artifacts.get(aid)
        duration=json.loads(art['probe'])['duration_s'];sid=body['speech_id']
        if self.speech.get(sid)['status']=='planned':
            self.speech._set(sid,status='voiced',artifact_id=aid,raw_artifact_id=aid,audio_sha256=art['sha256'],raw_audio_sha256=art['sha256'],duration_s=duration,raw_duration_s=duration,raw_alignment=source.get('alignment'))
        clock=RationalRate(**body['clock'])
        fit=self.speech.fit(sid,clock.num/clock.den)
        if not self.alignment.get(sid):self.alignment.align(sid,self.speech.get,now=utcnow())
        previous=self.s.db.uow().records.get('captionset','caps:'+sid)
        caps=json.loads(previous['body']) if previous else self.alignment.captions(sid,self.speech.get,fit['fit'],clock,fit['speech_hash'],now=utcnow()).to_dict()
        return {'speech':fit,'captions':caps}

    def approve(self,sid,body):
        return self.speech.approve(sid,body.get('speech_hash',''),body.get('reviewer',''))

    def attach(self,eid,revision,sids):
        """One new revision for a reviewed set; treatment validation still applies."""
        self.s._current(eid,revision,True)
        if not sids or not isinstance(sids,list):raise ContractError('speech_ids_required','speech_ids')
        variants={k:self.s.experiments._variant(eid,k) for k in 'ABCD'}
        segments={k:copy.deepcopy(v.segments) for k,v in variants.items()}
        for sid in sids:
            row=self.s.db.conn.execute('SELECT value FROM meta WHERE key=?',('speech-binding:'+sid,)).fetchone()
            if not row:raise ContractError('unknown_speech_binding','speech_id')
            binding=json.loads(row[0]);speech=self.speech.get(sid)
            if binding['experiment_id']!=eid or binding['revision']!=revision or speech['status']!='approved':raise ContractError('stale_or_unapproved_speech','speech_id')
            self.s.artifacts.verified_path(speech['artifact_id'])
            caps=self.s.detail('captionset','caps:'+sid)
            for key,items in segments.items():
                for seg in items:
                    if seg['id']==binding['segment_id'] and seg.get('copy')==speech['source_text'] and seg['target']==speech['target']:
                        seg['speech']={'artifact_id':speech['artifact_id'],'speech_hash':speech['speech_hash']}
                        if not seg.get('captions'):seg['captions']=[{k:c[k] for k in ('start_frame','end_frame','text')} for c in caps['cues']]
        branches=[{'key':k,'factor':v.changed_factor,'regions':[x.to_dict() if hasattr(x,'to_dict') else x for x in v.allowed_regions],
            'segments':segments[k],'hypothesis':v.hypothesis,'primary_metric':v.primary_metric,'allowed_fields':v.allowed_fields,'dependent_fields':v.dependent_fields} for k,v in variants.items() if k!='A']
        return self.s.patch_experiment_draft(eid,{'segments':segments['A'],'variants':branches,'reason':'Attach reviewed speech and fitted captions'},revision)
