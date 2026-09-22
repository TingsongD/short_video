from copy import deepcopy
from types import SimpleNamespace
import pytest
from modules.factory.analysis.source_evidence import SourceEvidenceService
from modules.factory.domain.errors import ContractError
from modules.factory.domain.records import content_hash
from modules.factory.store import Database
from test_factory_source_evidence import binding


def test_frozen_cumulative_envelope_and_two_clarifications_survive_restart(tmp_path):
    from modules.factory.analysis.analysis_envelope import AnalysisEnvelope
    db=Database(tmp_path/'db')
    try:
        store=SourceEvidenceService(db,tmp_path/'evidence')
        record=store.create('run',binding(),{'version':'test.v1'})
        for stage in ('clock','visual','audio','fusion'):
            store.chunk(record['id'],stage,0,1,lambda:{},current_binding=binding())
        complete=store.complete(record['id'],{k:1 for k in ('clock','visual','audio','fusion')},current_binding=binding())
        frozen={'evidence_sha256':complete['manifest']['sha256']}
        request={'scope':'whole','input':'actual request','binding':frozen}
        usage={'images':1,'windows':1,'media_seconds':'1','payload_bytes':10,'input_tokens_bound':10,'output_tokens_bound':10}
        adapter=SimpleNamespace(prepared=lambda req:([],usage))
        plan={'binding':{'evidence_sha256':complete['manifest']['sha256']},'requests':[request],
              'envelope':{'max_requests':3,'max_clarification_rounds':2,'max_images':3,'max_windows':3,
                          'max_media_seconds':'3','max_payload_bytes':30,'max_input_tokens':30,'max_output_tokens':30}}
        plan['identity']=content_hash(plan)
        ledger=AnalysisEnvelope(store,adapter)
        ledger.freeze(record['id'],plan)
        first=ledger.claim(record['id'],request)
        assert ledger.claim(record['id'],request)==first
        for i in range(2):
            ledger=AnalysisEnvelope(SourceEvidenceService(db,tmp_path/'evidence'),adapter)
            assert ledger.claim(record['id'],{'scope':'clarification','input':str(i),'binding':frozen})['clarification_round']==i+1
        with pytest.raises(ContractError,match='analysis_plan_conflict'):
            ledger.claim(record['id'],{'scope':'clarification','binding':{'evidence_sha256':'f'*64}})
        with pytest.raises(ContractError,match='analysis_envelope_exhausted'):
            ledger.claim(record['id'],{'scope':'clarification','input':'third','binding':frozen})
        # Unknown operations retain their exact identity, not a fresh round.
        assert ledger.claim(record['id'],request)==first
        changed=deepcopy(plan);changed['requests'][0]['input']='different'
        changed['identity']=content_hash({k:v for k,v in changed.items() if k!='identity'})
        with pytest.raises(ContractError,match='analysis_plan_conflict'):
            ledger.freeze(record['id'],changed)
    finally:
        db.close()
