"""Seed-bound quoted analysis and explicit collection of its durable receipt."""
from ..domain.errors import ContractError
from ..store.uow import utcnow


class AnalysisWork:
    def __init__(self,services):self.s=services

    def prepare(self,seed_id,body):
        seed=self.s.seeds.get(seed_id)
        if seed.evidence_status!='media_ready':raise ContractError('source_not_ready','seed_id')
        art=self.s.db.uow().artifacts.get(seed.source_asset_id)
        request={'seed_id':seed_id,'artifact_id':seed.source_asset_id,'artifact_sha256':art['sha256'],'model':body.get('model',''),'input_mode':'video+audio'}
        return self.s.effect_work.prepare('analysis',body.get('provider','audiovisual_analysis'),request['model'],[request])

    def queue_collect(self,seed_id,body):
        if not body.get('reviewer'):raise ContractError('reviewer_required','reviewer')
        return self.s.commands.enqueue('analysis_collect',{'seed_id':seed_id,'job_id':body.get('job_id',''),'reviewer':body['reviewer']},phase='analyze')

    def collect(self,body):
        command=self.s.commands.get(body['job_id'])
        if command['status']!='succeeded' or command['command']['kind']!='effect':raise ContractError('analysis_unfinished','job_id')
        cmd=command['command'];plan=self.s.effect_work.get(cmd['input']['plan_id'])
        if plan['kind']!='analysis':raise ContractError('analysis_scope_mismatch','job_id')
        req=next(op['request'] for op in plan['operations'] if op['key']==cmd['input']['operation'])
        seed=self.s.seeds.get(body['seed_id']);art=self.s.db.uow().artifacts.get(seed.source_asset_id)
        if req.get('seed_id')!=seed.id or req['artifact_id']!=seed.source_asset_id or req['artifact_sha256']!=art['sha256']:raise ContractError('analysis_scope_mismatch','seed')
        result=cmd['result']['result'];observations=result.get('analysis',result)
        return {'blueprint':self.s.analysis.import_observations(seed.id,observations,body['reviewer'],provenance={'analyzer':plan['provider'],'model':plan['model'],'attempt_id':cmd['result']['attempt_id']}).to_dict()}
