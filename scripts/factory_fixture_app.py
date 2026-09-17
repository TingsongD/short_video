"""Isolated, explicitly offline application for browser and process QA."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules.factory.bootstrap import bootstrap
from modules.factory.testing.durable import DiskDrive,DiskGeneration,CrashDrive,configure_faults
from modules.factory.services.worker import ApplicationWorker
from modules.factory.api import create_app

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--port',type=int,default=5197)
    parser.add_argument('--worker',action='store_true');args=parser.parse_args()
    root=Path(args.root).resolve()
    if not str(root).startswith('/tmp/') and not str(root).startswith('/private/tmp/'):
        raise SystemExit('This QA launcher requires a fresh /tmp root, never the operational workspace.')
    services=bootstrap(root,providers={'jimeng_canvas':DiskGeneration(root)},drive=CrashDrive(root),settings={'mode':'offline','drive_folder_id':'fixture-folder'})
    from modules.factory.providers.catalog import CapabilityCatalog,CapabilitySnapshot,snapshot_id
    from datetime import datetime,timedelta,timezone
    if not CapabilityCatalog(services.db).latest('jimeng_canvas','fixture-fast','','text'):
        CapabilityCatalog(services.db).put(CapabilitySnapshot(schema_version='capability_snapshot.v1',id=snapshot_id('jimeng_canvas','fixture-fast','','text'),created_at=datetime.now(timezone.utc).isoformat(),provider='jimeng_canvas',model='fixture-fast',input_mode='text',support='observed',capabilities=services.providers['jimeng_canvas'].capabilities('fixture-fast'),valid_until=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()))
    services.scheduler.lease_s=1
    if args.worker:configure_faults(services,root)
    if args.worker:ApplicationWorker(services).run()
    else:
        import uvicorn
        uvicorn.run(create_app(services),host='127.0.0.1',port=args.port)
