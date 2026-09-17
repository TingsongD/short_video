"""Durable supervisor for owned local tools, recoverable after worker death."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from ..domain.errors import ContractError
from ..providers.state import DurableState
from .service import ResourceRegistry
from ...batch.local import process_table, same_process


class OwnedRunner:
    def __init__(self,db,root,owner):
        self.db,self.root,self.owner=db,Path(root).resolve(),owner
        self.root.mkdir(parents=True,exist_ok=True)

    def __call__(self,argv,timeout=120,cwd=None):
        argv=list(map(str,argv)); cwd=str(Path(cwd or self.root).resolve())
        identity=hashlib.sha256(json.dumps([argv,cwd,self.owner]).encode()).hexdigest()
        file=self.root/(identity+'.json'); state=DurableState(file)
        if not state:
            state.update(argv=argv,cwd=cwd,owner=self.owner,timeout=timeout,status='prepared',resource_id='process-'+identity)
            state.flush()
        if state.get('status')=='prepared':
            # The supervisor claims the prepared intent atomically under flock.
            # Duplicate supervisor processes cannot both execute its command.
            proc=subprocess.Popen([sys.executable,'-m','modules.factory.resources.runner',self.db.path,str(file)],
                 cwd=Path(__file__).resolve().parents[3],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
            # Reap this child when possible; output/state survives its caller.
        else:
            proc=None
        deadline=time.monotonic()+timeout+5
        while time.monotonic()<deadline:
            state=DurableState(file)
            if state.get('status')=='done':
                if proc:
                    try: proc.wait(timeout=1)
                    except subprocess.TimeoutExpired: pass
                return subprocess.CompletedProcess(argv,state['returncode'],state.get('stdout',''),state.get('stderr',''))
            if state.get('status')=='running':
                identity_state=state.get('identity')
                if identity_state and not same_process(identity_state,process_table().get(identity_state['pid'])):
                    if DurableState(file).get('status')=='done': continue
                    raise ContractError('local_process_unresolved','process',state['resource_id'])
            time.sleep(.1)
        raise subprocess.TimeoutExpired(argv,timeout)


def supervise(db_path,state_path):
    from ..store import Database
    from .service import CleanupService
    import fcntl
    path=Path(state_path)
    with path.with_suffix('.supervisor.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return
        state=DurableState(path)
        if state.get('status')!='prepared': return
        db=Database(db_path); registry=ResourceRegistry(db)
        identity=process_table()[os.getpid()]
        registry.register(state['resource_id'],identity['pid'],identity['birth'],identity['command'],state['owner'],workspace=state['cwd'])
        state.update(status='running',identity=identity);state.flush()
        proc=subprocess.Popen(state['argv'],cwd=state['cwd'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        child=process_table().get(proc.pid)
        if child:
            registry.register(state['resource_id']+'-child',child['pid'],child['birth'],child['command'],state['owner'],workspace=state['cwd'])
        try:
            out,err=proc.communicate(timeout=state['timeout'])
            # CLI diagnostics are bounded and centrally redacted before storage.
            from ..events.redact import redact
            state.update(status='done',returncode=proc.returncode,stdout=redact(out[-4000000:]),stderr=redact(err[-200000:]))
            state.flush()
        except subprocess.TimeoutExpired:
            # Retain identity; the caller reports unresolved, never launches a
            # replacement merely because observation timed out.
            state.update(status='timed_out');state.flush()
            if child:
                CleanupService(registry).cleanup(state['owner'],resource_ids={state['resource_id']+'-child'})
            proc.wait(timeout=5)
        finally:
            if proc.poll() is not None and child: registry.set_status(state['resource_id']+'-child','stopped')
            registry.set_status(state['resource_id'],'stopped');db.close()


if __name__=='__main__':
    supervise(sys.argv[1],sys.argv[2])
