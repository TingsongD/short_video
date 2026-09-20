"""Explicit live construction after configuration and dated route qualification.

No credentials are read at import/startup in offline mode. Connection settings
are non-secret IDs; OAuth and Canvas native stores stay at transport boundaries.
"""
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from ..domain.errors import ContractError
from ..execution.policy import ExecutionPolicy
from .state import DurableState


def _observed_google_identity(creds):
    """Return the token principal's account identity without exposing secrets.

    ``google.oauth2.credentials.Credentials`` does not always retain the
    ``account`` field from an ``authorized_user`` ADC file (this gcloud
    writes ``account: ''`` even on a completed login).  The factory still
    needs the *token's own* identity to enforce the configured-account
    boundary, so recover it in order:

    1. credential attributes (``account`` / ``service_account_email``);
    2. the ``email`` claim of the ``id_token`` minted by the refresh —
       a signed statement by Google about this credential's principal
       (present when the grant includes the ``openid`` scope; decoded
       locally, no signature check needed since it arrived over the
       authenticated refresh channel moments ago);
    3. the ADC file's own declared identity (``account`` /
       ``client_email``).

    There is deliberately **no** fallback to the local gcloud
    configuration: ``config_default``'s account is the ``gcloud auth
    login`` identity — a different credential store than the ADC token's
    principal.  Borrowing it would report an account as verified while
    the token actually belongs to someone else (observed live: an ADC
    replaced by an interrupted login for another project's OAuth client
    passed the check, then every Vertex call returned IAM
    PERMISSION_DENIED).  When the credential's own identity cannot be
    observed, the check must fail closed — the operator re-authenticates
    ADC with an identity-bearing grant.
    """
    observed = (getattr(creds, 'account', None)
                or getattr(creds, 'service_account_email', None))
    if observed:
        return observed
    try:
        id_token = getattr(creds, 'id_token', None)
        if id_token:
            import base64
            body = id_token.split('.')[1]
            body += '=' * (-len(body) % 4)
            observed = json.loads(base64.urlsafe_b64decode(body)).get('email')
            if observed:
                return observed
    except Exception:
        pass
    try:
        from google.auth import _cloud_sdk
        path = (os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
                or _cloud_sdk.get_application_default_credentials_path())
        payload = json.loads(Path(path).read_text())
        return payload.get('account') or payload.get('client_email') or None
    except Exception:
        return None


def configured_adapters(db,data,mode,artifacts):
    file=Path(data)/'connections.json'
    if mode!='live' or not file.exists(): return {},None
    settings=json.loads(file.read_text()); adapters={}; drive=None
    enabled=set(settings.get('enabled',[]));policy=ExecutionPolicy(mode,frozenset(enabled))
    now=datetime.now(timezone.utc)
    for provider in enabled & {'jimeng_canvas','google_vertex'}:
        conn=settings.get(provider,{})
        if not conn.get('account_id'):continue
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
                observed=_observed_google_identity(creds)
                if not observed or observed!=identity:raise AuthError('account_mismatch_or_unavailable')
                return {'kind':'oauth','access_token':creds.token,'identity':observed,'project':project,
                        'scopes':['cloud-platform'],'expiry':creds.expiry.replace(tzinfo=timezone.utc).isoformat() if creds.expiry else None}
            adapter=VertexAdapter(VertexAuth(credentials,project),LiveVertexTransport(policy),state,
                conn['rates'],capabilities=caps,project=project,location=conn.get('location','global'))
        adapters[provider]=adapter
    drive_conn=settings.get('drive',{})
    try:drive_current=datetime.fromisoformat(drive_conn['qualified_until'].replace('Z','+00:00'))>now
    except (KeyError,ValueError,TypeError):drive_current=False
    if 'drive' in enabled and drive_current and drive_conn.get('account_id') and drive_conn.get('contract_evidence') and drive_conn.get('live_evidence'):
        from ..integrations.drive import GdriveCLI
        drive=GdriveCLI(policy=policy,expected_account=drive_conn['account_id'])
    return adapters,drive


def configured_auxiliary(root,data,mode,artifacts=None):
    """Optional qualified routes. Offline startup constructs no live transport."""
    if mode!='live':return {},None,None,{}
    file=Path(data)/'connections.json'
    if not file.exists():return {},None,None,{}
    from ..operations.config import credential_loader
    settings=json.loads(file.read_text());enabled=set(settings.get('enabled',[]))
    policy=ExecutionPolicy(mode,frozenset(enabled));providers={};publisher=None;analytics=None;extra={}
    def qualified(name):
        conn=settings.get(name,{})
        try:valid=datetime.fromisoformat(conn['qualified_until'].replace('Z','+00:00'))>datetime.now(timezone.utc)
        except (KeyError,ValueError,TypeError):valid=False
        return conn if name in enabled and conn.get('contract_evidence') and conn.get('live_evidence') and valid and conn.get('account_id') else None
    conn=qualified('audiovisual_analysis')
    if conn and conn.get('project') and conn.get('model') and conn.get('pricing') and artifacts:
        from ..analysis.vertex import VertexAnalyzer
        from .vertex_auth import VertexAuth,AuthError
        identity,project=conn['account_id'],conn['project']
        def credentials(project=project,identity=identity):
            import google.auth
            from google.auth.transport.requests import Request
            creds,_=google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform']);creds.refresh(Request())
            observed=_observed_google_identity(creds)
            if observed!=identity:raise AuthError('account_mismatch_or_unavailable')
            return {'kind':'oauth','identity':observed,'project':project,'scopes':['cloud-platform'],'access_token':creds.token}
        providers['audiovisual_analysis']=VertexAnalyzer(Path(data)/'providers/analysis',artifacts,VertexAuth(credentials,project),identity,project,conn['model'],conn['pricing'],location=conn.get('location','global'),policy=policy,max_bytes=conn.get('max_bytes',20*1024*1024))
    conn=qualified('shopify')
    if conn and conn.get('shop') and artifacts:
        from ..integrations.shopify import configured_shopify
        from ..products.importer import ProductImporter
        from .shopify import ShopifyImport
        adapter=configured_shopify(conn['shop'],credential_loader(root,['SHOPIFY_ADMIN_ACCESS_TOKEN']),policy)
        providers['shopify']=ShopifyImport(Path(data)/'providers/shopify',ProductImporter(artifacts.db,artifacts,adapter,conn['shop']),conn['account_id'])
    conn=qualified('elevenlabs')
    if conn and conn.get('pricing') and conn.get('model')=='eleven_v3':
        from .elevenlabs import ElevenLabsAdapter
        providers['elevenlabs']=ElevenLabsAdapter(Path(data)/'providers/elevenlabs',credential_loader(root,['ELEVENLABS_API_KEY']),policy=policy,account=conn['account_id'],pricing=conn['pricing'])
        providers['elevenlabs'].qualified=True
    conn=qualified('generated_music')
    if conn and conn.get('pricing') and conn.get('model'):
        from .music import MusicAdapter
        providers['generated_music']=MusicAdapter(Path(data)/'providers/music',credential_loader(root,['ELEVENLABS_API_KEY']),policy=policy,account=conn['account_id'],pricing=conn['pricing'],model=conn['model'])
    conn=qualified('publish')
    if conn and conn.get('user') and conn.get('accounts'):
        from ..integrations.publisher import UploadPostPublisher
        credentials=credential_loader(root,['UPLOAD_POST_API_KEY','UPLOAD_POST_KEY'])
        publisher=UploadPostPublisher(user=conn['user'],policy=policy,credentials=lambda credentials=credentials:credentials().get('UPLOAD_POST_API_KEY') or credentials().get('UPLOAD_POST_KEY'))
        extra['publication_accounts']=conn['accounts']
    conn=qualified('youtube_analytics')
    if conn:
        from ..analytics.client import FactoryAnalyticsClient
        from ..integrations.http import BoundedHTTP
        from urllib.parse import urlsplit,parse_qsl,urlencode,urlunsplit
        http=BoundedHTTP('youtube_analytics',policy,32*1024*1024)
        credentials=credential_loader(root,['YOUTUBE_API_KEY'])
        identity=conn['account_id']
        def transport(request):
            url=request['url'];parts=urlsplit(url)
            if parts.scheme!='https' or parts.hostname not in ('www.googleapis.com','youtubeanalytics.googleapis.com','youtubereporting.googleapis.com') or parts.username or parts.port not in (None,443):raise ContractError('invalid_analytics_host','url')
            import google.auth
            from google.auth.transport.requests import Request
            creds,_=google.auth.default(scopes=['https://www.googleapis.com/auth/yt-analytics.readonly','https://www.googleapis.com/auth/youtube.readonly'])
            creds.refresh(Request())
            observed=_observed_google_identity(creds)
            if observed!=identity:raise ContractError('analytics_account_mismatch','account')
            query=dict(parse_qsl(parts.query,keep_blank_values=True))
            if 'key' in query:
                key=credentials()['YOUTUBE_API_KEY']
                if key:query['key']=key
                else:query.pop('key')
                url=urlunsplit((*parts[:3],urlencode(query),parts.fragment))
            headers={**request.get('headers',{}),'Authorization':'Bearer '+creds.token}
            payload=json.dumps(request.get('json') or request.get('body')).encode() if request.get('json') or request.get('body') else None
            if payload:headers['Content-Type']='application/json'
            status,reply_headers,raw=http(request.get('method','GET'),url,payload,headers)
            body=raw.decode() if request.get('format')=='csv' else json.loads(raw)
            return {'status':status,'body':body}
        analytics=FactoryAnalyticsClient(transport=transport)
        from .reporting import ReportingSetup
        providers["youtube_reporting"]=ReportingSetup(Path(data)/"providers/reporting",analytics,identity)
        if publisher is not None and publisher.verifier is None:
            # Verified manual registration needs platform-native post
            # inspection; the analytics route's OAuth transport already
            # scopes youtube.readonly, so it can back the verifier.
            from ..integrations.publisher import youtube_post_verifier
            publisher.verifier=youtube_post_verifier(transport)
    for name,adapter in providers.items():
        connection=settings.get('youtube_analytics' if name=='youtube_reporting' else name,{})
        adapter.qualified=True
        adapter.contract_evidence=connection.get('contract_evidence')
    return providers,publisher,analytics,extra
