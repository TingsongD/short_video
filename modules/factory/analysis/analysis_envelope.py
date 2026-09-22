"""Persistent request bounds, separate from normal monetary reservations.

Claiming an identical request returns the same identity even after an unknown
provider outcome. This ledger never releases money or resubmits an operation.
"""
from fractions import Fraction
import json

from .source_evidence import SourceEvidence
from ..domain.errors import ContractError
from ..domain.records import content_hash


class AnalysisEnvelope:
    def __init__(self,store,adapter):
        self.store,self.adapter=store,adapter

    def freeze(self,evidence_id,plan):
        if plan.get('identity')!=content_hash({k:v for k,v in plan.items() if k!='identity'}):
            raise ContractError('analysis_plan_conflict','identity')
        with self.store.db.uow() as u:
            row=u.records.get('sourceevidence',evidence_id)
            record=SourceEvidence(**self.store.get(evidence_id))
            if record.status!='complete' or record.manifest['sha256']!=plan['binding']['evidence_sha256']:
                raise ContractError('analysis_evidence_unavailable','plan')
            if record.analysis_plan:
                saved=self.store.blobs.read(record.analysis_plan)
                if saved['identity']!=plan['identity']:
                    raise ContractError('analysis_plan_conflict','plan')
                return saved
            record.analysis_plan=self.store.blobs.put(plan)
            u.records.put(record,expected_version=row['version'])
            return plan

    def claim(self,evidence_id,request):
        _,usage=self.adapter.prepared(request)
        key=content_hash(request)
        with self.store.db.uow() as u:
            row=u.records.get('sourceevidence',evidence_id)
            record=SourceEvidence(**self.store.get(evidence_id))
            if not record.analysis_plan:
                raise ContractError('analysis_envelope_missing','authorization')
            plan=self.store.blobs.read(record.analysis_plan)
            if request.get('binding')!=plan['binding']:
                raise ContractError('analysis_plan_conflict','binding')
            prior=next((r for r in record.analysis_requests if r['request_hash']==key),None)
            if prior:
                return prior
            initial=key in {content_hash(r) for r in plan['requests']}
            if not initial and request.get('scope')!='clarification':
                raise ContractError('analysis_plan_conflict','request')
            rounds=sum(r['clarification_round']>0 for r in record.analysis_requests)
            entry={'request_hash':key,'effect_key':content_hash([evidence_id,key]),'usage':usage,
                   'clarification_round':0 if initial else rounds+1}
            entries=record.analysis_requests+[entry]
            bounds=plan['envelope']
            exceeded=(len(entries)>bounds['max_requests'] or entry['clarification_round']>bounds['max_clarification_rounds'])
            for field,maximum in [('images','max_images'),('windows','max_windows'),('payload_bytes','max_payload_bytes'),
                                  ('input_tokens_bound','max_input_tokens'),('output_tokens_bound','max_output_tokens')]:
                exceeded |= sum(e['usage'][field] for e in entries)>bounds[maximum]
            exceeded |= sum((Fraction(e['usage']['media_seconds']) for e in entries),Fraction(0))>Fraction(bounds['max_media_seconds'])
            if exceeded:
                raise ContractError('analysis_envelope_exhausted','source_evidence',
                                    'Frozen cumulative bounds exhausted; unresolved essential evidence requires a new quote.')
            record.analysis_requests=entries
            u.records.put(record,expected_version=row['version'])
            return entry
