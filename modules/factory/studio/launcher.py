"""Pinned, isolated local Studio launch with durable process identity."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from ..domain.errors import ContractError
from ..providers.state import DurableState
from ..resources.service import scan_listeners
from ...batch.local import process_table, same_process, descendants

LAUNCHER=Path(__file__).resolve().parents[3]/'scripts/hypit.sh'
LOCAL_PROFILE={'format':'hypit.runtime-local@1','dataRoot':'.hypit/runtimes/local','endpoints':{
    'media.local':{'use':'@hypit/provider-media-local','config':{'defaultConcurrency':1}},
    'hyperframes.local':{'use':'@hypit/provider-hyperframes-local','config':{'workers':1,'defaultConcurrency':1,'browserCapacity':1}}}}


def prepare_local(workspace,runner=None):
    workspace=Path(workspace);profile=workspace/'hypit.runtime.json'
    if not profile.exists(): profile.write_text(json.dumps(LOCAL_PROFILE))
    elif json.loads(profile.read_text())!=LOCAL_PROFILE:
        raise ContractError('runtime_profile_changed','profile','Use the isolated local profile')
    selected=workspace/'.hypit/runtime'
    if not selected.exists():
        run=runner or (lambda argv,**kw:subprocess.run(argv,capture_output=True,text=True,**kw))
        result=run([str(LAUNCHER),'runtime','use',str(profile),'--workspace',str(workspace),'--json'],timeout=30,cwd=workspace)
        if result.returncode: raise ContractError('runtime_setup_failed','hypit')
    return profile


def capture_owned(registry,owner,workspace,roots=()):
    table=process_table(); marker=str(Path(workspace).resolve())
    matched={pid for pid,row in table.items() if marker+'/.hypit/' in row['command']}
    selected=descendants(table,matched|set(roots));ports=scan_listeners()
    for pid in selected:
        row=table.get(pid)
        if not row or pid==os.getpid():continue
        import hashlib
        rid='local-'+hashlib.sha256(f"{pid}:{row['birth']}".encode()).hexdigest()[:24]
        if not registry.get(rid): registry.register(rid,pid,row['birth'],row['command'],owner,workspace=marker,
                                                  ports=[p for p,holder in ports.items() if holder==pid])


class LocalStudioLauncher:
    def __init__(self,registry,root): self.registry,self.root=registry,Path(root)

    def closed(self,session_id):
        state=DurableState(self.root/(session_id+'.json'))
        with state.locked():
            if state:
                state.update(status='closed',identity=None);state.flush()

    def launch(self,composition_ws,owner,session_id):
        workspace=self.root/session_id;state=DurableState(self.root/(session_id+'.json'))
        with state.locked():
            if not state:
                shutil.copytree(composition_ws,workspace,ignore=shutil.ignore_patterns('.hypit','.factory-build*'),dirs_exist_ok=True)
                prepare_local(workspace)
                state.update(status='prepared',workspace=str(workspace));state.flush()
            table=process_table()
            if state.get('identity') and same_process(state['identity'],table.get(state['identity']['pid'])):
                return {**state['identity'],'port':state.get('port'),'url':state.get('url'),'workspace':str(workspace)}
            if state['status'] in ('starting','open'):
                # Never launch another process after an uncertain acceptance.
                matches=[r for r in table.values() if str(workspace/'render.svrun') in r['command'] and 'studio' in r['command']]
                if len(matches)!=1:raise ContractError('studio_launch_unresolved','session_id',session_id)
                identity=matches[0]
            else:
                state.update(status='starting');state.flush()
                log=workspace/'studio.log'
                # A new launch may pick a different port; old output cannot
                # serve as readiness evidence for this launch.
                if log.exists():log.rename(workspace/f'studio-{time.time_ns()}.log')
                with log.open('a') as output:
                    proc=subprocess.Popen([str(LAUNCHER),'studio','--run',str(workspace/'render.svrun'),
                        '--workspace',str(workspace),'--runtime',str(workspace/'hypit.runtime.json'),'--port','5189'],
                        cwd=workspace,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                identity=None
                for _ in range(20):
                    identity=process_table().get(proc.pid)
                    if identity:break
                    time.sleep(.05)
                if not identity:raise ContractError('studio_launch_failed','process')
                state.update(identity=identity);state.flush()
                capture_owned(self.registry,owner,workspace,[identity['pid']])
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                raw=(workspace/'studio.log').read_text() if (workspace/'studio.log').exists() else ''
                urls=re.findall(r'(https?://(?:localhost|127\.0\.0\.1):(\d+))',raw)
                if urls:
                    base,number=urls[-1];port=int(number);url=base+'/#comments'
                    current=process_table().get(identity['pid'])
                    if current:identity=current
                    capture_owned(self.registry,owner,workspace,[identity['pid']])
                    state.update(status='open',identity=identity,port=port,url=url);state.flush()
                    return {**identity,'port':port,'url':url,'workspace':str(workspace)}
                time.sleep(.1)
            raise ContractError('studio_start_unresolved','session_id',session_id)
