"""Explicit Reporting API setup through the same durable effect boundary."""
from datetime import datetime,timedelta,timezone
from .synchronous import SynchronousAdapter
from .state import DurableState
from ..domain.errors import ContractError


class ReportingSetup(SynchronousAdapter):
    def __init__(self,root,client,account):super().__init__(root);self.client,self.account=client,account
    def price(self,request):
        if request.get('report_type')!='channel_reach_basic_a1' or not request.get('name'):raise ContractError('invalid_report_setup','request')
        return {'kind':'usage_estimate','unit':'usd_micros','amount':0,'reserve_amount':0,'rate_basis':'Reporting job configuration: no provider usage charge; explicit account authorization required','valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
    def execute(self,request):
        job=self.client.create_reach_job(request['name'])
        return {'job':job},None,{'actual_usd_micros':0}
    def reconcile(self,operation_id=None,request_hash=None):
        receipt=super().reconcile(operation_id,request_hash)
        if not receipt or receipt['status']!='unknown':return receipt
        # Discover an accepted configuration; never create a second reporting job.
        name=receipt.get('request',{}).get('name')
        jobs=[job for job in self.client.reach_jobs() if name and job.get('name')==name]
        if len(jobs)!=1:return receipt
        state=DurableState(self.root/receipt['operation_id']/'receipt.json')
        state.update(status='succeeded',result={'job':jobs[0]},actual_usd_micros=0);state.flush()
        return dict(state)
