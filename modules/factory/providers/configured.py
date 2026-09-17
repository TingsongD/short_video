"""Explicit live construction after configuration and dated route qualification.

No credentials are read at import/startup in offline mode. Connection settings
are non-secret IDs; OAuth and Canvas native stores stay at transport boundaries.
"""
import json
from datetime import datetime,timezone
from pathlib import Path
from ..domain.errors import ContractError
from ..execution.policy import ExecutionPolicy
from .state import DurableState


def configured_adapters(db,data,mode,artifacts):
    file=Path(data)/'connections.json'
    if mode!='live' or not file.exists(): return {},None
    settings=json.loads(file.read_text()); adapters={}; drive=None
    enabled=set(settings.get('enabled',[]));policy=ExecutionPolicy(mode,frozenset(enabled))
    now=datetime.now(timezone.utc)
    for provider in enabled & {'jimeng_canvas','google_vertex'}:
        conn=settings.get(provider,{})
        rows=db.conn.execute("SELECT body FROM records WHERE kind='capabilitysnapshot' AND json_extract(body,'$.provider')=? ORDER BY revision DESC",(provider,)).fetchall()
        caps={};seen=set()
        for row in rows:
            snap=json.loads(row[0]); model=snap['model']
            route=(model,snap.get('location'),snap.get('input_mode'))
            if route in seen:continue
            seen.add(route)
            try:valid=datetime.fromisoformat(snap['valid_until'].replace('Z','+00:00'))>now
            except (KeyError,ValueError,TypeError):valid=False
            if snap['support']=='qualified' and valid and snap.get('input_mode') in conn.get('input_modes',[]) and snap.get('location','')==conn.get('location',''):
                caps.setdefault(model,{**snap['capabilities'],'live_qualified':True,'qualified_modes':[]})['qualified_modes'].append(snap['input_mode'])
        if not caps:continue
        state=DurableState(Path(data)/'providers'/f'{provider}.json')
        if provider=='jimeng_canvas':
            from ...assets.canvas_cli import CanvasCLI
            from .canvas import CanvasAdapter
            adapter=CanvasAdapter(CanvasCLI(profile=conn.get('profile','default'),region=conn.get('region','cn')),
                  state,expected_user=conn.get('account_id'),policy=policy,artifacts=artifacts)
            adapter.set_capabilities(caps)
        else:
            from .vertex import VertexAdapter,LiveVertexTransport
            from .vertex_auth import VertexAuth,AuthError
            project=conn.get('project'); identity=conn.get('account_id')
            if not project or not identity or not conn.get('rates'):continue
            def credentials(project=project,identity=identity):
                import google.auth
                from google.auth.transport.requests import Request
                creds,default_project=google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
                creds.refresh(Request())
                observed=getattr(creds,'account',None) or getattr(creds,'service_account_email',None)
                if not observed or observed!=identity:raise AuthError('account_mismatch_or_unavailable')
                return {'kind':'oauth','access_token':creds.token,'identity':observed,'project':project,
                        'scopes':['cloud-platform'],'expiry':creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None}
            adapter=VertexAdapter(VertexAuth(credentials,project),LiveVertexTransport(policy),state,
                conn['rates'],capabilities=caps,project=project,location=conn.get('location','global'))
        adapters[provider]=adapter
    if 'drive' in enabled and settings.get('drive',{}).get('contract_evidence'):
        from ..integrations.drive import GdriveCLI
        drive=GdriveCLI(policy=policy)
    return adapters,drive
