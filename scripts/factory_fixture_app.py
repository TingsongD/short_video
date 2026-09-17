"""Isolated, explicitly offline application for browser and process QA."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules.factory.bootstrap import bootstrap
from modules.factory.testing.durable import DiskDrive
from modules.factory.services.worker import ApplicationWorker
from modules.factory.api import create_app

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True);parser.add_argument('--port',type=int,default=5197)
    parser.add_argument('--worker',action='store_true');args=parser.parse_args()
    root=Path(args.root).resolve()
    if not str(root).startswith('/tmp/') and not str(root).startswith('/private/tmp/'):
        raise SystemExit('This QA launcher requires a fresh /tmp root, never the operational workspace.')
    services=bootstrap(root,drive=DiskDrive(root/'fake-remote-drive'),settings={'mode':'offline','drive_folder_id':'fixture-folder'})
    if args.worker:ApplicationWorker(services).run()
    else:
        import uvicorn
        uvicorn.run(create_app(services),host='127.0.0.1',port=args.port)
