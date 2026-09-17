"""Disk-backed external-service fixtures; never selected by production bootstrap."""
import hashlib
import json
from pathlib import Path
import shutil
import uuid


class DiskDrive:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
    def list_files(self,parent):
        return [json.loads(p.read_text()) for p in self.root.glob('*.json') if json.loads(p.read_text())['parent']==parent]
    def stat(self,fid):
        p=self.root/(fid+'.json');return json.loads(p.read_text()) if p.exists() else None
    def upload(self,parent,path,name):
        fid=uuid.uuid4().hex;dest=self.root/(fid+'.mp4');shutil.copy2(path,dest)
        meta={'id':fid,'name':name,'parent':parent,'size':dest.stat().st_size,'md5':hashlib.md5(dest.read_bytes()).hexdigest()}
        (self.root/(fid+'.json')).write_text(json.dumps(meta));return {'id':fid}
    def link(self,fid):return 'https://drive.invalid/file/'+fid


def barrier(root, point):
    """Test-only crash latch. Never configured by the production bootstrap."""
    import time
    root=Path(root);config=root/'fault.json';marker=root/'fault-reached.json'
    if not config.exists() or marker.exists() or json.loads(config.read_text()).get('point')!=point:return
    marker.write_text(json.dumps({'point':point,'at':time.time()}))
    while not (root/'fault-release').exists():time.sleep(.02)


class DiskGeneration:
    """Durable remote fake with actual local video bytes and no submit dedup."""
    name='jimeng_canvas';account='fixture-account';models=['fixture-fast']
    def __init__(self,root,name='jimeng_canvas'):
        self.name=name;self.root=Path(root);self.remote=self.root/('fake-generation' if name=='jimeng_canvas' else 'fake-vertex');self.remote.mkdir(parents=True,exist_ok=True)
    def readiness(self):return {'ready':True,'installed':True,'authenticated':True,'contract_tested':True,'live_qualified':False,'catalog_visible':True}
    def capabilities(self,model):return {'durations_s':[1,3,5,10],'aspects':['9:16'],'resolutions':['180x320'],'references':{},'audio':False}
    def price(self,request,duration_s,model=None):
        from ..domain.money import Money
        return Money('jimeng_credits' if self.name=='jimeng_canvas' else 'usd_micros',1)
    def submit(self,request,price=None):
        import fcntl
        from ..execution.effects import wire_hash
        with (self.remote/'lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            oid=uuid.uuid4().hex
            row={'operation_id':oid,'request_hash':wire_hash(request),'status':'accepted','actual_credits':1,'request':request}
            tmp=self.remote/(oid+'.tmp');tmp.write_text(json.dumps(row));tmp.replace(self.remote/(oid+'.json'))
        barrier(self.root,'accepted')
        return row
    def poll(self,oid):
        row=json.loads((self.remote/(oid+'.json')).read_text());row['status']='accepted' if (self.root/'hold-remote').exists() else 'succeeded'
        if self.name=='google_vertex':row['actual_usd_micros']=row.pop('actual_credits')
        return row
    observe=poll
    def reconcile(self,operation_id=None,request_hash=None):
        if operation_id:return self.poll(operation_id)
        hits=[json.loads(p.read_text()) for p in self.remote.glob('*.json') if json.loads(p.read_text())['request_hash']==request_hash]
        return self.poll(hits[0]['operation_id']) if len(hits)==1 else None
    def download(self,oid,destination=None):
        barrier(self.root,'download')
        row=self.poll(oid);path=self.remote/(oid+'.mp4')
        if not path.exists():
            from .fixtures import _moving_mp4
            _moving_mp4(path,row['request']['duration_s'],size='180x320')
        payload=path.read_bytes()
        if destination:Path(destination).write_bytes(payload)
        return {'bytes':payload,'sha256':hashlib.sha256(payload).hexdigest()}


class CrashDrive(DiskDrive):
    def __init__(self,root):
        self.test_root=Path(root);super().__init__(self.test_root/'fake-remote-drive')
    def upload(self,parent,path,name):
        out=super().upload(parent,path,name);barrier(self.test_root,'upload');return out


def configure_faults(services,root):
    """Patch only explicitly launched isolated QA workers."""
    root=Path(root)
    old=services.executor.submit
    def submit(*args,**kwargs):
        barrier(root,'before_submission');return old(*args,**kwargs)
    services.executor.submit=submit
    from ..resources.runner import OwnedRunner
    original=OwnedRunner.__call__
    def owned(self,argv,*args,**kwargs):
        import threading,time
        # Slow only this isolated render fixture so SIGKILL occurs during work.
        config=root/'fault.json'
        if config.exists() and json.loads(config.read_text()).get('point')=='render' and '-i' in argv and '-re' not in argv:
            argv=list(argv);argv.insert(argv.index('-i'),'-re')
        result=[];errors=[]
        def run():
            try:result.append(original(self,argv,*args,**kwargs))
            except BaseException as e:errors.append(e)
        if argv[0]=='ffmpeg' and config.exists() and json.loads(config.read_text()).get('point')=='render' and not (root/'fault-reached.json').exists():
            thread=threading.Thread(target=run);thread.start()
            deadline=time.monotonic()+20
            while time.monotonic()<deadline and thread.is_alive():
                running=[p for p in self.root.glob('*.json') if json.loads(p.read_text()).get('status')=='running']
                if running:
                    barrier(root,'render');break
                time.sleep(.01)
            thread.join()
            if errors:raise errors[0]
            return result[0]
        return original(self,argv,*args,**kwargs)
    OwnedRunner.__call__=owned
