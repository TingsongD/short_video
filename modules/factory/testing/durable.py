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
