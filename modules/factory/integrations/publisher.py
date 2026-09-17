"""Upload Post native multipart, async receipt and per-platform contracts.

Source: docs.upload-post.com/api/{upload-video,upload-status,edit-post,unpublish-post}.
Publication identity is client assigned before transmission. Status reads never
repeat uploads. Platform inspection uses an injected native platform verifier.
"""
import json
import uuid
from pathlib import Path
from urllib.parse import urlencode
from ..testing.fakes import ProviderError

UPLOAD_PATH='/api/upload'
STATUS_PATH='/api/uploadposts/status'
DEFAULT_BASE='https://api.upload-post.com'
TERMINAL={'public','failed','draft','scheduled'}
ACCEPTED={'accepted','queued','uploading','processing'}


class PublishTransportError(ProviderError):
    def __init__(self,message,status_code=0,body=None):
        super().__init__(message,http_status=status_code or None);self.status_code=status_code;self.body=body


def http_transport(request):
    from .http import BoundedHTTP
    headers=dict(request['headers']);data=None
    if request.get('json') is not None:
        data=json.dumps(request['json']).encode();headers['Content-Type']='application/json'
    elif request['method']=='POST':
        boundary=uuid.uuid4().hex;body=bytearray()
        for name,value in request['fields'].items():
            for v in value if isinstance(value,(tuple,list)) else [value]:
                body.extend((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{v}\r\n').encode())
        f=request.get('file')
        if f:
            body.extend((f'--{boundary}\r\nContent-Disposition: form-data; name="video"; filename="final.mp4"\r\nContent-Type: video/mp4\r\n\r\n').encode())
            body.extend(f['bytes']);body.extend(b'\r\n')
        body.extend(f'--{boundary}--\r\n'.encode());data=bytes(body)
        headers['Content-Type']=f'multipart/form-data; boundary={boundary}'
    http=BoundedHTTP('publish',request['policy'],4*1024*1024)
    status,_,raw=http(request['method'],request['base_url']+request['path'],data,headers)
    if status>=400:raise PublishTransportError('upload_post_http_error',status)
    try:return {'status':status,'body':json.loads(raw)}
    except (ValueError,TypeError):raise PublishTransportError('malformed_upload_response') from None


class UploadPostPublisher:
    def __init__(self,api_key='',user='',base_url=DEFAULT_BASE,transport=None,policy=None,credentials=None,verifier=None):
        self.api_key,self.user,self.base_url=api_key,user,base_url
        self.credentials,self.verifier,self.policy=credentials,verifier,policy
        from ..execution.policy import live_transport
        self.transport=transport or live_transport(http_transport,'publish',policy)

    def readiness(self):
        issues=[] if (self.api_key or self.credentials) and self.user else ['missing_credentials_or_user']
        return {'provider':'upload_post','configured':not issues,'problems':issues}

    def _send(self,method,path,fields=None,file=None,body=None,headers=None):
        key=self.credentials() if self.credentials else self.api_key
        response=self.transport({'method':method,'path':path,'base_url':self.base_url,'policy':self.policy,
            'headers':{'Authorization':'Apikey '+key,**(headers or {})},'fields':fields or {},'file':file,'json':body})
        if not isinstance(response,dict) or response.get('status',200)>=400:raise PublishTransportError('upload_post_http_error',response.get('status',0))
        if not isinstance(response.get('body'),dict):raise PublishTransportError('malformed_upload_response')
        return response['body']

    def upload(self,*,video_path='',video_url='',title='',description='',platforms=(),visibility='public',schedule_date='',user='',idempotency_key='',extra_fields=None):
        user=user or self.user
        if not user or not platforms or not idempotency_key or bool(video_path)==bool(video_url):raise ValueError('user, platforms, stable identity and exactly one media source are required')
        fields={'user':user,'platform[]':list(platforms),'title':title,'description':description,
                'request_id':idempotency_key,'async_upload':'true','privacyStatus':'private' if visibility=='draft' else visibility}
        if schedule_date:fields['scheduled_date']=schedule_date
        extras=dict(extra_fields or {})
        if set(extras)&{'user','platform[]','request_id','async_upload','video','scheduled_date','privacyStatus'}:raise ValueError('reserved upload fields')
        fields.update(extras)
        file=None
        if video_path:
            p=Path(video_path)
            if p.stat().st_size>200*1024*1024:raise ValueError('video exceeds bounded upload size')
            file={'name':'video','filename':p.name,'content_type':'video/mp4','bytes':p.read_bytes()}
        else:fields['video']=video_url
        body=self._send('POST',UPLOAD_PATH,fields,file,headers={'Idempotency-Key':idempotency_key,'X-Request-Id':idempotency_key})
        rid=body.get('request_id') or idempotency_key
        if body.get('request_id') and body['request_id']!=idempotency_key:raise PublishTransportError('request_identity_mismatch')
        out=self._normalise(body,rid,platforms[0]);out['visibility']=visibility
        if body.get('job_id'):out.update(job_id=body['job_id'],status='scheduled',scheduled_at=schedule_date)
        return out

    def _normalise(self,body,rid,platform):
        top=body.get('status');results=body.get('results') or []
        if isinstance(results,dict):results=[{'platform':k,**v} for k,v in results.items() if isinstance(v,dict)]
        if not isinstance(results,list):raise PublishTransportError('malformed_platform_results')
        result=next((r for r in results if isinstance(r,dict) and r.get('platform')==platform),{})
        out={'request_id':rid,'status':'unknown','platform_results':results}
        if result.get('skipped') or result.get('success') is False or result.get('status') in ('failed','skipped'):
            return {**out,'status':'failed','error':result.get('error') or result.get('skip_reason') or 'platform_failed'}
        if result.get('fallback_to_inbox') or result.get('privacyStatus') in ('private','unlisted'):
            return {**out,'status':'draft'}
        pid=result.get('video_id') or result.get('post_id') or result.get('id')
        url=result.get('post_url') or result.get('url');at=result.get('published_at') or result.get('upload_timestamp')
        if result.get('success') is True and pid and url and url.startswith('https://') and at:
            return {**out,'status':'public','remote_post_id':str(pid),'post_url':url,'published_at':at}
        mapping={'pending':'accepted','queued':'queued','processing':'processing','in_progress':'processing','completed':'unknown','failed':'failed','not_found':'unknown'}
        out['status']=mapping.get(top,'accepted' if body.get('request_id') or body.get('job_id') else 'unknown')
        return out

    def status(self,request_id,platform='youtube',job_id=''):
        query={'job_id':job_id} if job_id else {'request_id':request_id}
        body=self._send('GET',STATUS_PATH+'?'+urlencode(query))
        return self._normalise(body,request_id,platform)

    def find_by_idempotency_key(self,idempotency_key,platform='youtube'):
        return self.status(idempotency_key,platform)

    def verify_post(self,post_ref):
        if self.verifier is None:raise PublishTransportError('platform_verifier_unavailable')
        return self.verifier(post_ref)

    def update_post(self,post_ref,fields,*,platform='youtube',user=''):
        body={'platform':platform,'user':user or self.user,'post_id':post_ref,**fields}
        result=self._send('POST','/api/uploadposts/posts/edit',body=body)
        if result.get('success') is not True:raise PublishTransportError('edit_not_confirmed')
        return result

    def delete_post(self,post_ref,*,platform='youtube',user=''):
        result=self._send('POST','/api/uploadposts/posts/unpublish',body={'platform':platform,'user':user or self.user,'post_id':post_ref})
        if result.get('success') is not True:raise PublishTransportError('deletion_not_confirmed')
        return result
