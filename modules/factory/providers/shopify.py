"""Explicit read-only catalog acquisition with durable import receipts."""
from datetime import datetime,timedelta,timezone
from .synchronous import SynchronousAdapter
from ..domain.errors import ContractError


class ShopifyImport(SynchronousAdapter):
    def __init__(self,root,importer,account):
        super().__init__(root);self.importer,self.account=importer,account

    def price(self,request):
        selection=request.get('selection')
        if request.get('shop')!=self.importer.shop or not isinstance(selection,list) or not 1<=len(selection)<=50 or any(not isinstance(x,str) or not x for x in selection):
            raise ContractError('explicit_product_selection_required','selection','Select up to 50 product handles or IDs from the configured store')
        return {'kind':'usage_estimate','unit':'usd_micros','amount':0,'reserve_amount':0,'rate_basis':'Read-only Admin catalog import; no per-call API fee','valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}

    def execute(self,request):
        self.price(request)
        return self.importer.import_catalog(request['selection']),None,{'actual_usd_micros':0}
